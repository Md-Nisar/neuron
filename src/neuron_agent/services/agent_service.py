"""Transport-independent agent application service."""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from collections.abc import AsyncGenerator, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Protocol

import anyio
import psycopg
import structlog
from langchain_core.messages import AIMessageChunk

from neuron_agent.config.settings import Settings
from neuron_agent.errors.base import (
    AppError,
    CapacityError,
    PersistenceError,
    RunTimeoutError,
    ShuttingDownError,
    ThreadBusyError,
    ThreadNotFoundError,
)
from neuron_agent.graphs.main_graph import build_graph
from neuron_agent.observability.logging import bind_correlation_context
from neuron_agent.persistence.checkpointer import Persistence, build_persistence
from neuron_agent.schemas.agent import AgentAnswer, AgentRequest, AgentResponse
from neuron_agent.security.input_policy import validate_user_message
from neuron_agent.services.streaming import AnswerTokenExtractor, StreamEvent, tool_call_names

logger = structlog.get_logger(__name__)


class StopSignal(Protocol):
    """Anything with an awaitable `wait()`, e.g. `anyio.Event` or `asyncio.Event`."""

    async def wait(self) -> Any: ...


class RunLease:
    """A run's claim on its thread and (for streams) a concurrency slot. Idempotent release."""

    def __init__(self, release: Callable[[], None]) -> None:
        self._release: Callable[[], None] | None = release

    def release(self) -> None:
        if self._release is not None:
            release, self._release = self._release, None
            release()


@dataclass(frozen=True)
class PreparedRun:
    """A validated run whose thread has been resolved and claimed; nothing has executed yet.

    The caller must run it (`invoke`/`stream` release the lease when done) or release
    `lease` itself.
    """

    request_id: str
    thread_id: str
    run_id: str
    graph_input: dict[str, Any]
    lease: RunLease

    @property
    def config(self) -> dict[str, Any]:
        return {"configurable": {"thread_id": self.thread_id}}


class AgentService:
    """Invoke the graph behind a stable application boundary."""

    def __init__(self, settings: Settings, persistence: Persistence | None = None) -> None:
        self._settings = settings
        self._persistence = persistence or build_persistence(settings)
        self._graph: Any | None = None
        # Process-local run guards (ADR 0005 decisions 5 and 6); not shared across replicas.
        self._active_threads: set[str] = set()
        self._open_streams = 0
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

    async def prepare(self, request: AgentRequest, *, streaming: bool = False) -> PreparedRun:
        """Validate, resolve and claim the request's thread. Raises `AppError` before any output."""
        request_id = str(uuid.uuid4())
        run_id = str(uuid.uuid4())
        user_id_hash = _hash_identifier(request.user_id) if request.user_id else None
        message = validate_user_message(request.message, max_chars=self._settings.max_prompt_chars)
        bind_correlation_context(request_id=request_id, thread_id=request.thread_id, run_id=run_id)
        with self._persistence_errors():
            thread_id = await self._resolve_thread(request.thread_id, user_id_hash)
        bind_correlation_context(request_id=None, thread_id=thread_id)
        lease = self._claim(thread_id, streaming=streaming)
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
            lease=lease,
        )

    async def invoke(self, request: AgentRequest) -> AgentResponse:
        run = await self.prepare(request)
        try:
            with self._persistence_errors():
                async with asyncio.timeout(self._settings.run_timeout_seconds):
                    result = await self.graph.ainvoke(run.graph_input, config=run.config)
        except TimeoutError as exc:
            logger.warning("agent_run_timed_out")
            raise RunTimeoutError("agent run exceeded its time budget") from exc
        finally:
            run.lease.release()
        return _response(run, result["answer"])

    async def stream(
        self, run: PreparedRun, *, stop: StopSignal | None = None
    ) -> AsyncGenerator[StreamEvent]:
        """Execute a prepared run, yielding the ADR 0005 event sequence.

        Always yields `run_started` first and `done` last. Between them come `token` and
        `tool_call` events, then exactly one of `final` (success) or `error` (failure,
        timeout, or `stop` being set during shutdown).

        The graph runs in a producer task. If this generator is cancelled or closed (the
        client disconnected), times out, or is stopped, that task is cancelled so model and
        tool calls stop. The thread's history is unaffected: turns commit only on success.
        """
        bind_correlation_context(
            request_id=run.request_id, thread_id=run.thread_id, run_id=run.run_id
        )
        queue: asyncio.Queue[StreamEvent | None] = asyncio.Queue()
        producer = asyncio.create_task(self._produce(run, queue))
        stop_waiter = asyncio.ensure_future(stop.wait()) if stop is not None else None
        deadline = asyncio.get_running_loop().time() + self._settings.run_timeout_seconds
        try:
            yield StreamEvent(
                "run_started",
                {"request_id": run.request_id, "thread_id": run.thread_id, "run_id": run.run_id},
            )
            while True:
                getter = asyncio.ensure_future(queue.get())
                waiters = {getter} if stop_waiter is None else {getter, stop_waiter}
                remaining = deadline - asyncio.get_running_loop().time()
                done, _ = await asyncio.wait(
                    waiters, timeout=max(remaining, 0), return_when=asyncio.FIRST_COMPLETED
                )
                if getter not in done:
                    getter.cancel()
                    await _cancel(producer)
                    if stop_waiter is not None and stop_waiter in done:
                        logger.info("agent_stream_stopped_for_shutdown")
                        yield _error_event(ShuttingDownError("server is shutting down"))
                    else:
                        logger.warning("agent_run_timed_out")
                        yield _error_event(RunTimeoutError("agent run exceeded its time budget"))
                    break
                event = getter.result()
                if event is None:
                    break
                yield event
            yield StreamEvent("done")
        finally:
            if not producer.done():
                logger.info("agent_stream_cancelled")
                await _cancel(producer)
            if stop_waiter is not None:
                stop_waiter.cancel()
            run.lease.release()

    async def _produce(self, run: PreparedRun, queue: asyncio.Queue[StreamEvent | None]) -> None:
        """Run the graph, translating its stream into events; always ends with `None`."""
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
                        queue.put_nowait(StreamEvent("tool_call", {"name": name}))
                    if delta := extractor.feed(message):
                        queue.put_nowait(StreamEvent("token", {"text": delta}))
        except AppError as exc:
            queue.put_nowait(_error_event(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception("agent_stream_unexpected_error", error_type=type(exc).__name__)
            queue.put_nowait(
                StreamEvent("error", {"code": "internal_server_error", "retryable": False})
            )
        else:
            if answer is None:
                logger.error("agent_stream_missing_answer")
                queue.put_nowait(
                    StreamEvent("error", {"code": "internal_server_error", "retryable": False})
                )
            else:
                queue.put_nowait(StreamEvent("final", _response(run, answer).model_dump()))
        finally:
            queue.put_nowait(None)

    def _claim(self, thread_id: str, *, streaming: bool) -> RunLease:
        """Claim the thread (reject-on-busy) and, for streams, a concurrency slot.

        The busy guard applies only with persistence: without it, `thread_id` is just a
        correlation ID and concurrent runs share no state.
        """
        guard_thread = self._persistence.checkpointer is not None
        if streaming and self._open_streams >= self._settings.max_concurrent_streams:
            logger.warning(
                "agent_stream_capacity_exceeded", limit=self._settings.max_concurrent_streams
            )
            raise CapacityError("too many concurrent streams")
        if guard_thread and thread_id in self._active_threads:
            logger.info("agent_thread_busy")
            raise ThreadBusyError("a run is already in progress on this thread")
        if streaming:
            self._open_streams += 1
        if guard_thread:
            self._active_threads.add(thread_id)

        def release() -> None:
            if streaming:
                self._open_streams -= 1
            if guard_thread:
                self._active_threads.discard(thread_id)

        return RunLease(release)

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


# Upper bound on waiting for a cancelled run to unwind (LangGraph cancels its node tasks).
_CANCEL_GRACE_SECONDS = 5.0


async def _cancel(task: asyncio.Task[Any]) -> None:
    """Cancel `task` exactly once and wait (bounded) for it to unwind.

    The caller is often itself being cancelled, e.g. by sse-starlette's anyio cancel scope
    when the client disconnects. A plain `await task` would then fail immediately and, on
    every retry, forward another `cancel()` to `task`; repeated cancellation interrupts
    LangGraph's own cleanup, which then abandons the running model call. `asyncio.wait`
    never forwards cancellation, and the shielded scope lets the wait complete.
    """
    task.cancel()
    with anyio.CancelScope(shield=True), anyio.move_on_after(_CANCEL_GRACE_SECONDS):
        await asyncio.wait({task})


def _hash_identifier(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
