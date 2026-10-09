"""Transport-independent agent application service."""

from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from collections.abc import AsyncGenerator, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Protocol

import anyio
import psycopg
import structlog
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage

from neuron_agent.config.settings import Settings
from neuron_agent.errors.base import (
    AppError,
    AuthenticationError,
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
from neuron_agent.schemas.agent import (
    AgentAnswer,
    AgentRequest,
    AgentResponse,
    ThreadHistoryResponse,
    ThreadMessage,
)
from neuron_agent.security.auth import Principal, principal_owner_key
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

    async def prepare(
        self,
        request: AgentRequest,
        *,
        streaming: bool = False,
        principal: Principal | None = None,
    ) -> PreparedRun:
        """Validate, resolve and claim the request's thread. Raises `AppError` before any output."""
        request_id = str(uuid.uuid4())
        run_id = str(uuid.uuid4())
        owner_key = self._owner_key(request.user_id, principal)
        message = validate_user_message(request.message, max_chars=self._settings.max_prompt_chars)
        bind_correlation_context(request_id=request_id, thread_id=request.thread_id, run_id=run_id)
        with self._persistence_errors():
            thread_id = await self._resolve_thread(request.thread_id, owner_key)
        bind_correlation_context(request_id=None, thread_id=thread_id)
        lease = self._claim(thread_id, streaming=streaming)
        owner_state = (
            {"owner_key": owner_key}
            if self._settings.auth_mode == "jwt"
            else {"user_id_hash": owner_key}
        )
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
                **owner_state,
            },
            lease=lease,
        )

    async def invoke(
        self, request: AgentRequest, *, principal: Principal | None = None
    ) -> AgentResponse:
        run = await self.prepare(request, principal=principal)
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

        The graph runs in a producer task that also enforces `APP_RUN_TIMEOUT_SECONDS`. If
        this generator is cancelled or closed (the client disconnected) or stopped, that task
        is cancelled so model and tool calls stop. The thread's history is unaffected: turns
        commit only on success.
        """
        bind_correlation_context(
            request_id=run.request_id, thread_id=run.thread_id, run_id=run.run_id
        )
        stats = _StreamStats(
            ids={"request_id": run.request_id, "thread_id": run.thread_id, "run_id": run.run_id}
        )
        logger.info("stream_started", **stats.ids)
        queue: asyncio.Queue[StreamEvent | None] = asyncio.Queue()
        producer = asyncio.create_task(self._produce(run, queue))
        stop_waiter = asyncio.ensure_future(stop.wait()) if stop is not None else None
        try:
            yield stats.record(
                StreamEvent(
                    "run_started",
                    {
                        "request_id": run.request_id,
                        "thread_id": run.thread_id,
                        "run_id": run.run_id,
                    },
                )
            )
            while True:
                getter = asyncio.ensure_future(queue.get())
                waiters = {getter} if stop_waiter is None else {getter, stop_waiter}
                done, _ = await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
                if getter not in done:
                    getter.cancel()
                    await _cancel(producer)
                    stats.termination = "shutdown"
                    yield stats.record(_error_event(ShuttingDownError("server is shutting down")))
                    break
                event = getter.result()
                if event is None:
                    break
                yield stats.record(event)
            stats.finished = True
            yield stats.record(StreamEvent("done"))
        finally:
            if not producer.done():
                await _cancel(producer)
            if stop_waiter is not None:
                stop_waiter.cancel()
            run.lease.release()
            stats.log()

    async def _produce(self, run: PreparedRun, queue: asyncio.Queue[StreamEvent | None]) -> None:
        """Run the graph, translating its stream into events; always ends with `None`.

        The run budget is enforced here rather than by the consumer, so it holds even when
        the client stops reading and the generator is parked at a `yield`.
        """
        extractor = AnswerTokenExtractor()
        answer: AgentAnswer | None = None
        try:
            async with asyncio.timeout(self._settings.run_timeout_seconds):
                with self._persistence_errors():
                    async for namespace, mode, chunk in self.graph.astream(
                        run.graph_input,
                        config=run.config,
                        stream_mode=["messages", "updates"],
                        # The create_agent loop runs as a nested graph inside the `agent`
                        # node; its model tokens are only surfaced with subgraphs enabled.
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
        except TimeoutError:
            logger.warning("agent_run_timed_out")
            queue.put_nowait(_error_event(RunTimeoutError("agent run exceeded its time budget")))
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
            # Unbounded queue: its size is bounded by the run's own output
            # (APP_MAX_OUTPUT_TOKENS per model call, APP_MAX_AGENT_ITERATIONS calls).
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

    async def _resolve_thread(self, thread_id: str | None, owner_key: str | None) -> str:
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
        await self._owned_thread_state(thread_id, owner_key)
        return thread_id

    async def get_history(
        self,
        thread_id: str,
        user_id: str | None,
        *,
        limit: int,
        offset: int,
        principal: Principal | None = None,
    ) -> ThreadHistoryResponse:
        """Return a page of the thread's user/assistant turns, oldest first.

        Only `HumanMessage`/`AIMessage` turns with text are exposed; system prompts, tool
        calls and tool results are never returned.
        """
        owner_key = self._owner_key(user_id, principal)
        bind_correlation_context(request_id=None, thread_id=thread_id)
        with self._persistence_errors():
            values = await self._owned_thread_state(thread_id, owner_key)
        turns = [
            ThreadMessage(
                role="user" if isinstance(message, HumanMessage) else "assistant",
                content=message.content,
            )
            for message in values.get("messages", [])
            if isinstance(message, HumanMessage | AIMessage)
            and isinstance(message.content, str)
            and message.content
        ]
        return ThreadHistoryResponse(
            thread_id=thread_id,
            messages=turns[offset : offset + limit],
            total=len(turns),
            limit=limit,
            offset=offset,
        )

    async def delete_thread(
        self, thread_id: str, user_id: str | None, *, principal: Principal | None = None
    ) -> None:
        """Delete every checkpoint of an owned thread. Rejected while a run is in flight."""
        owner_key = self._owner_key(user_id, principal)
        bind_correlation_context(request_id=None, thread_id=thread_id)
        with self._persistence_errors():
            await self._owned_thread_state(thread_id, owner_key)
            if thread_id in self._active_threads:
                # The in-flight run would re-create the thread with its final write.
                logger.info("agent_thread_busy")
                raise ThreadBusyError("a run is already in progress on this thread")
            checkpointer = self._persistence.checkpointer
            # _owned_thread_state already raised if there is no checkpointer.
            assert checkpointer is not None  # nosec B101
            await checkpointer.adelete_thread(thread_id)
        logger.info("thread_deleted")

    async def _owned_thread_state(self, thread_id: str, owner_key: str | None) -> dict[str, Any]:
        """Return the thread's state if it exists and belongs to the effective owner.

        A missing thread, another user's thread, and a service without persistence all raise
        the same `ThreadNotFoundError`, so thread IDs cannot be probed.
        """
        if self._persistence.checkpointer is None:
            raise ThreadNotFoundError("thread not found")
        snapshot = await self.graph.aget_state({"configurable": {"thread_id": thread_id}})
        owner_field = "owner_key" if self._settings.auth_mode == "jwt" else "user_id_hash"
        if not snapshot.values or snapshot.values.get(owner_field) != owner_key:
            logger.info("thread_access_denied")
            raise ThreadNotFoundError("thread not found")
        values: dict[str, Any] = snapshot.values
        return values

    def _owner_key(self, user_id: str | None, principal: Principal | None) -> str | None:
        """Resolve the owner without allowing request identity to override JWT identity."""
        if self._settings.auth_mode == "jwt":
            if principal is None or self._settings.identity_hash_key is None:
                raise AuthenticationError("authenticated principal is required")
            return principal_owner_key(
                principal, self._settings.identity_hash_key.get_secret_value()
            )
        return _hash_identifier(user_id) if user_id else None


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


@dataclass
class _StreamStats:
    """Per-stream telemetry: counts, time to first token, and how the stream ended.

    Logged once when the stream ends: `stream_completed` (with `termination` = completed,
    error, timeout, or shutdown) or `stream_cancelled` (the client disconnected before
    `done`). Only counts and codes are logged, never streamed text.
    """

    ids: dict[str, str]
    started: float = field(default_factory=time.monotonic)
    first_token_ms: float | None = None
    tokens: int = 0
    events: int = 0
    termination: str | None = None
    error_code: str | None = None
    finished: bool = False

    def record(self, event: StreamEvent) -> StreamEvent:
        self.events += 1
        if event.event == "token":
            self.tokens += 1
            if self.first_token_ms is None:
                self.first_token_ms = self._elapsed_ms()
        elif event.event == "final":
            self.termination = "completed"
        elif event.event == "error":
            self.error_code = event.data.get("code")
            if self.termination is None:
                self.termination = "timeout" if self.error_code == "run_timeout" else "error"
        return event

    def log(self) -> None:
        fields: dict[str, Any] = {
            **self.ids,
            "duration_ms": self._elapsed_ms(),
            "ttft_ms": self.first_token_ms,
            "tokens_streamed": self.tokens,
            "events_streamed": self.events,
        }
        if not self.finished:
            logger.info("stream_cancelled", termination="client_disconnect", **fields)
            return
        log = logger.info if self.termination == "completed" else logger.warning
        log("stream_completed", termination=self.termination, error_code=self.error_code, **fields)

    def _elapsed_ms(self) -> float:
        return round((time.monotonic() - self.started) * 1000, 2)


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
