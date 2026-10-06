"""Transport-independent agent application service."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import psycopg
import structlog
from langchain_core.messages import AIMessageChunk

from neuron_agent.config.settings import Settings
from neuron_agent.errors.base import AppError, PersistenceError, ThreadNotFoundError
from neuron_agent.graphs.main_graph import build_graph
from neuron_agent.observability.logging import bind_correlation_context
from neuron_agent.persistence.checkpointer import Persistence, build_persistence
from neuron_agent.schemas.agent import AgentAnswer, AgentRequest, AgentResponse
from neuron_agent.security.input_policy import validate_user_message
from neuron_agent.services.streaming import AnswerTokenExtractor, StreamEvent, tool_call_names

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class PreparedRun:
    """A validated run whose thread has been resolved; nothing has executed yet."""

    request_id: str
    thread_id: str
    run_id: str
    graph_input: dict[str, Any]

    @property
    def config(self) -> dict[str, Any]:
        return {"configurable": {"thread_id": self.thread_id}}


class AgentService:
    """Invoke the graph behind a stable application boundary."""

    def __init__(self, settings: Settings, persistence: Persistence | None = None) -> None:
        self._settings = settings
        self._persistence = persistence or build_persistence(settings)
        self._graph: Any | None = None
        if self._persistence.is_open:
            self._graph = build_graph(settings, checkpointer=self._persistence.checkpointer)

    async def startup(self) -> None:
        """Open persistence resources (connection pool) before serving requests."""
        if self._persistence.is_open:
            return
        await self._persistence.open(run_setup=self._settings.checkpointer_setup_on_startup)
        self._graph = build_graph(self._settings, checkpointer=self._persistence.checkpointer)

    async def shutdown(self) -> None:
        """Release persistence resources."""
        if self._persistence.pool is not None:
            await self._persistence.close()
            self._graph = None

    @property
    def graph(self) -> Any:
        """The compiled graph; unavailable until a database-backed service is started."""
        if self._graph is None:
            raise PersistenceError("thread persistence is not started")
        return self._graph

    async def is_ready(self) -> bool:
        """Return whether the service's dependencies are reachable."""
        return await self._persistence.is_ready()

    async def prepare(self, request: AgentRequest) -> PreparedRun:
        """Validate the request and resolve its thread. Raises `AppError` before any output."""
        request_id = str(uuid.uuid4())
        run_id = str(uuid.uuid4())
        user_id_hash = _hash_identifier(request.user_id) if request.user_id else None
        message = validate_user_message(request.message, max_chars=self._settings.max_prompt_chars)
        bind_correlation_context(request_id=request_id, thread_id=request.thread_id, run_id=run_id)
        with self._persistence_errors():
            thread_id = await self._resolve_thread(request.thread_id, user_id_hash)
        bind_correlation_context(request_id=None, thread_id=thread_id)
        return PreparedRun(
            request_id=request_id,
            thread_id=thread_id,
            run_id=run_id,
            graph_input={
                "messages": [],
                "user_message": message,
                "request_id": request_id,
                "thread_id": thread_id,
                "run_id": run_id,
                "user_id_hash": user_id_hash,
            },
        )

    async def invoke(self, request: AgentRequest) -> AgentResponse:
        run = await self.prepare(request)
        with self._persistence_errors():
            result = await self.graph.ainvoke(run.graph_input, config=run.config)
        return _response(run, result["answer"])

    async def stream(self, run: PreparedRun) -> AsyncIterator[StreamEvent]:
        """Execute a prepared run, yielding the ADR 0005 event sequence.

        Always yields `run_started` first and `done` last. Between them come `token` and
        `tool_call` events, then exactly one of `final` (success) or `error` (failure).
        """
        bind_correlation_context(
            request_id=run.request_id, thread_id=run.thread_id, run_id=run.run_id
        )
        yield StreamEvent(
            "run_started",
            {"request_id": run.request_id, "thread_id": run.thread_id, "run_id": run.run_id},
        )
        extractor = AnswerTokenExtractor()
        answer: AgentAnswer | None = None
        try:
            with self._persistence_errors():
                async for namespace, mode, chunk in self.graph.astream(
                    run.graph_input,
                    config=run.config,
                    stream_mode=["messages", "updates"],
                    # The create_agent loop runs as a nested graph inside the `agent` node;
                    # its model tokens are only surfaced with subgraphs enabled.
                    subgraphs=True,
                ):
                    if mode == "updates" and not namespace and "agent" in chunk:
                        answer = chunk["agent"]["answer"]
                        continue
                    if mode != "messages" or not namespace:
                        continue
                    message, metadata = chunk
                    if not isinstance(message, AIMessageChunk):
                        continue
                    if metadata.get("langgraph_node") != "model":
                        continue
                    for name in tool_call_names(message):
                        yield StreamEvent("tool_call", {"name": name})
                    if delta := extractor.feed(message):
                        yield StreamEvent("token", {"text": delta})
        except AppError as exc:
            yield _error_event(exc)
        except Exception as exc:  # noqa: BLE001
            logger.exception("agent_stream_unexpected_error", error_type=type(exc).__name__)
            yield StreamEvent("error", {"code": "internal_server_error", "retryable": False})
        else:
            if answer is None:
                logger.error("agent_stream_missing_answer")
                yield StreamEvent("error", {"code": "internal_server_error", "retryable": False})
            else:
                yield StreamEvent("final", _response(run, answer).model_dump())
        yield StreamEvent("done")

    @contextmanager
    def _persistence_errors(self) -> Iterator[None]:
        """Classify checkpointer (psycopg) failures as `PersistenceError`."""
        try:
            yield
        except psycopg.Error as exc:
            logger.warning(
                "checkpointer_operation_failed",
                backend=self._persistence.backend,
                error_type=type(exc).__name__,
            )
            raise PersistenceError("thread persistence failed") from exc

    async def _resolve_thread(self, thread_id: str | None, user_id_hash: str | None) -> str:
        """Return the thread to run on, enforcing ADR 0005's thread rules.

        Without a thread ID the server mints a new UUID. With persistence enabled, a supplied
        ID must name an existing thread owned by the same (hashed) user; a missing thread and
        another user's thread raise the same `ThreadNotFoundError`, so IDs cannot be probed.
        Without persistence, a supplied ID is only a correlation ID.
        """
        if thread_id is None:
            return str(uuid.uuid4())
        if self._persistence.checkpointer is None:
            return thread_id
        snapshot = await self.graph.aget_state({"configurable": {"thread_id": thread_id}})
        if not snapshot.values or snapshot.values.get("user_id_hash") != user_id_hash:
            logger.info("thread_access_denied")
            raise ThreadNotFoundError("thread not found")
        return thread_id


def _response(run: PreparedRun, answer: AgentAnswer) -> AgentResponse:
    return AgentResponse(
        request_id=run.request_id,
        thread_id=run.thread_id,
        answer=answer.answer,
        used_tools=answer.used_tools,
        confidence=answer.confidence,
    )


def _error_event(exc: AppError) -> StreamEvent:
    """Map an `AppError` to an `error` event using the same visibility rules as HTTP."""
    log = logger.exception if exc.context.alert else logger.warning
    log("agent_stream_failed", error_code=exc.context.code, error_type=type(exc).__name__)
    code = exc.context.code if exc.context.user_visible else "internal_server_error"
    return StreamEvent("error", {"code": code, "retryable": exc.context.retryable})


def _hash_identifier(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
