# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Transport-independent agent application service."""

from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from collections.abc import AsyncGenerator, Iterator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import anyio
import psycopg
import structlog
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langgraph.types import Command, Interrupt, StateSnapshot
from opentelemetry import trace
from opentelemetry.trace import Span

from neuron_agent.config.settings import Settings
from neuron_agent.errors.base import (
    AppError,
    ApprovalNotFoundError,
    ApprovalPendingError,
    AuthenticationError,
    CapacityError,
    ConcurrentRunsExceededError,
    ExportTooLargeError,
    MemoryDisabledError,
    MemoryNotFoundError,
    PersistenceError,
    QuotaExceededError,
    RunTimeoutError,
    ShuttingDownError,
    ThreadBusyError,
    ThreadNotFoundError,
)
from neuron_agent.graphs.main_graph import build_graph
from neuron_agent.memory.store import Memory, MemoryStore, memory_id_key
from neuron_agent.memory.tools import memory_specs
from neuron_agent.observability import metrics, semconv, telemetry
from neuron_agent.observability.audit import audit
from neuron_agent.observability.logging import bind_correlation_context
from neuron_agent.persistence.checkpointer import Persistence, build_persistence
from neuron_agent.persistence.guards import build_run_guard, build_token_budget
from neuron_agent.persistence.run_guard import PostgresRunGuard
from neuron_agent.persistence.thread_index import OwnedThreadPage, owned_threads
from neuron_agent.persistence.thread_meta import derive_title
from neuron_agent.schemas.agent import (
    AgentAnswer,
    AgentRequest,
    AgentResponse,
    ApprovalRequest,
    ApprovalRequiredResponse,
    ExportedThread,
    FeedbackResponse,
    MemoriesResponse,
    MemoryErasureResponse,
    MemoryItem,
    PendingAction,
    ThreadHistoryResponse,
    ThreadMessage,
    ThreadTitleResponse,
    ToolCallRecord,
    UserDataErasureResponse,
    UserDataExportResponse,
    UserThreadsResponse,
    UserThreadSummary,
)
from neuron_agent.security.auth import Principal, principal_owner_key
from neuron_agent.security.authorization import (
    DEV_PERMISSIONS,
    AuthorizationContext,
    TokenUsageAccumulator,
)
from neuron_agent.security.input_policy import audit_tool_name, validate_user_message
from neuron_agent.security.output_policy import SYSTEM_PROMPT_REFUSAL, StreamLeakGuard
from neuron_agent.security.run_guard import RunClaimDenied, RunDenialReason, RunGuard, RunLease
from neuron_agent.security.usage_budget import BudgetReservation, TokenBudget
from neuron_agent.services.streaming import AnswerTokenExtractor, StreamEvent, tool_call_names
from neuron_agent.tools.registry import ToolRegistry, builtin_registry

logger = structlog.get_logger(__name__)


def estimate_prompt_tokens(message: str) -> int:
    """A deliberately high token estimate of the user message (UTF-8 bytes / 3, at least 1)."""
    return max(1, -(-len(message.encode()) // 3))


class StopSignal(Protocol):
    """Anything with an awaitable `wait()`, e.g. `anyio.Event` or `asyncio.Event`."""

    async def wait(self) -> Any: ...


@dataclass(frozen=True)
class PreparedRun:
    """A validated run whose thread has been resolved and claimed; nothing has executed yet.

    The caller must run it (`invoke`/`stream` release the lease when done) or release
    `lease` itself.
    """

    request_id: str
    thread_id: str
    run_id: str
    graph_input: Any
    authorization: AuthorizationContext
    budget_key: str
    budget_reservation: BudgetReservation
    checkpoint_owner: str | None
    created_thread: bool
    lease: RunLease
    # Set for a run that creates its thread: stored as the thread's title once the run succeeds.
    title: str | None = None

    @property
    def config(self) -> dict[str, Any]:
        config: dict[str, Any] = {"configurable": {"thread_id": self.thread_id}}
        if self.checkpoint_owner is not None:
            config["metadata"] = {"owner": self.checkpoint_owner}
        return config


class AgentService:
    """Invoke the graph behind a stable application boundary."""

    def __init__(
        self,
        settings: Settings,
        persistence: Persistence | None = None,
        token_budget: TokenBudget | None = None,
        run_guard: RunGuard | None = None,
    ) -> None:
        self._settings = settings
        self._persistence = persistence or build_persistence(settings)
        self._token_budget = token_budget or build_token_budget(settings, self._persistence)
        self._run_guard = run_guard or build_run_guard(settings, self._persistence)
        self._graph: Any | None = None
        # The tool set the graph was built with; None means the builtin tools.
        self._registry: ToolRegistry | None = None
        self._memory: MemoryStore | None = None
        self._drain_started: float | None = None
        self._in_flight = 0
        if self._persistence.is_open:
            self._compose_tools()
            self._graph = build_graph(
                settings, checkpointer=self._persistence.checkpointer, registry=self._registry
            )

    def use_registry(self, registry: ToolRegistry) -> None:
        """Serve `registry` (builtin plus MCP tools) from the next `startup`."""
        self._registry = registry
        self._memory = None

    def _compose_tools(self) -> None:
        """Add the memory tools to the registry once the store exists (ADR 0009 decision 7)."""
        store = self._persistence.store
        if store is None or self._memory is not None:
            return
        self._memory = MemoryStore(
            store,
            id_key=memory_id_key(self._settings),
            max_items=self._settings.memory_max_items,
            max_chars=self._settings.memory_max_chars,
            ttl_days=self._settings.memory_ttl_days,
        )
        self._registry = ToolRegistry([*self._tools(), *memory_specs(self._memory)])

    async def startup(self) -> None:
        """Open persistence resources (connection pool) and build the graph.

        An in-memory service already has a graph; it is rebuilt only for a `use_registry` tool set.
        """
        opened = not self._persistence.is_open
        if opened:
            await self._persistence.open(run_setup=self._settings.checkpointer_setup_on_startup)
        self._compose_tools()
        if opened or self._registry is not None:
            self._graph = build_graph(
                self._settings,
                checkpointer=self._persistence.checkpointer,
                registry=self._registry,
            )
        if opened and isinstance(self._run_guard, PostgresRunGuard):
            self._run_guard.start()

    async def shutdown(self) -> None:
        """Release persistence resources."""
        if isinstance(self._run_guard, PostgresRunGuard):
            await self._run_guard.close()
        if self._persistence.pool is not None:
            await self._persistence.close()
            self._graph = None

    def _tools(self) -> ToolRegistry:
        return self._registry or builtin_registry()

    @property
    def graph(self) -> Any:
        """The compiled graph; unavailable until a database-backed service is started."""
        if self._graph is None:
            raise PersistenceError("thread persistence is not started")
        return self._graph

    @property
    def draining(self) -> bool:
        """Whether shutdown has begun (`begin_drain` was called)."""
        return self._drain_started is not None

    async def is_ready(self) -> bool:
        """Return whether the service takes traffic: not draining, dependencies reachable."""
        return self._drain_started is None and await self._persistence.is_ready()

    def begin_drain(self) -> None:
        """Start refusing traffic for shutdown (ADR 0008 decision 4). Idempotent; never raises.

        Readiness turns false at once; new runs are refused once `APP_SHUTDOWN_DRAIN_SECONDS`
        have passed; runs already in flight are untouched. Safe in a signal handler: it only
        sets a flag, and the log line is emitted from the event loop when one is running.
        """
        with suppress(Exception):  # shutdown must proceed whatever happens here
            if self._drain_started is not None:
                return
            self._drain_started = time.monotonic()
            in_flight = self._in_flight
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                self._log_draining(in_flight)
            else:
                loop.call_soon_threadsafe(self._log_draining, in_flight)

    def _log_draining(self, in_flight: int) -> None:
        logger.info(
            "service_draining",
            in_flight_runs=in_flight,
            drain_seconds=self._settings.shutdown_drain_seconds,
        )

    def _refusing_new_runs(self) -> bool:
        return (
            self._drain_started is not None
            and time.monotonic() - self._drain_started >= self._settings.shutdown_drain_seconds
        )

    async def prepare(
        self,
        request: AgentRequest,
        *,
        streaming: bool = False,
        principal: Principal | None = None,
        usage: TokenUsageAccumulator | None = None,
    ) -> PreparedRun:
        """Validate, resolve and claim the request's thread. Raises `AppError` before any output."""
        if self._refusing_new_runs():
            raise ShuttingDownError("server is shutting down")
        request_id = str(uuid.uuid4())
        run_id = str(uuid.uuid4())
        owner_key = self._owner_key(request.user_id, principal)
        message = validate_user_message(request.message, max_chars=self._settings.max_prompt_chars)
        budget_key = owner_key or "anonymous"
        reservation = await self._reserve_budget(
            budget_key, self._settings.max_output_tokens + estimate_prompt_tokens(message)
        )
        try:
            bind_correlation_context(
                request_id=request_id, thread_id=request.thread_id, run_id=run_id
            )
            with self._persistence_errors():
                thread_id = await self._resolve_thread(request.thread_id, owner_key)
            bind_correlation_context(request_id=None, thread_id=thread_id)
            lease = self._count_in_flight(
                await self._claim(thread_id, streaming=streaming, owner_key=budget_key),
                reservation,
            )
        except BaseException:
            # No run will happen: give the reservation back (shielded, never raises).
            await self._token_budget.settle(reservation, 0)
            raise
        owner_state = (
            {"owner_key": owner_key}
            if self._settings.auth_mode == "jwt"
            else {"user_id_hash": owner_key}
        )
        if request.thread_id is not None and self._can_pause():
            try:
                with self._persistence_errors():
                    if await self._pending_interrupts(thread_id):
                        raise ApprovalPendingError("the thread waits for a decision on a tool call")
            except BaseException:
                await lease.release()
                raise
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
            authorization=self._authorization(owner_key, principal, usage),
            budget_key=budget_key,
            budget_reservation=reservation,
            checkpoint_owner=owner_key,
            created_thread=request.thread_id is None,
            lease=lease,
            title=derive_title(message) if request.thread_id is None else None,
        )

    async def _name_new_thread(self, run: PreparedRun) -> None:
        """File the first message's title under the thread; a failure never fails the run."""
        if run.title is None or run.checkpoint_owner is None:
            return
        try:
            await self._persistence.thread_titles.set_if_absent(
                run.checkpoint_owner, run.thread_id, run.title
            )
        except Exception as exc:  # noqa: BLE001 - a title is a convenience, the answer stands
            logger.warning("thread_title_failed", error_type=type(exc).__name__)

    def _audit_thread_created(self, run: PreparedRun) -> None:
        if run.created_thread:
            audit(
                "thread_created",
                outcome="allowed",
                actor=run.budget_key[:12] if self._settings.auth_mode == "jwt" else None,
                issuer_id=self._settings.auth_issuer_id,
                action="agent:invoke",
                resource_type="thread",
                resource_id=run.thread_id,
                request_id=run.request_id,
                run_id=run.run_id,
            )

    async def _reserve_budget(self, budget_key: str, tokens: int) -> BudgetReservation:
        """Reserve `tokens` of the owner's budget, or raise `QuotaExceededError`."""
        decision = await self._token_budget.reserve(budget_key, tokens)
        if not decision.allowed or decision.reservation is None:
            metrics.record_policy_block("token_budget")
            logger.warning(
                "user_limit_exceeded",
                limit_type="token_budget",
                owner_key_prefix=budget_key[:12],
                retry_after=decision.retry_after_seconds,
            )
            audit(
                "limit_exceeded",
                outcome="denied",
                actor=budget_key[:12] if self._settings.auth_mode == "jwt" else None,
                issuer_id=self._settings.auth_issuer_id,
                action="agent:invoke",
                resource_type="agent",
                reason="token_budget",
            )
            raise QuotaExceededError(decision.retry_after_seconds)
        return decision.reservation

    def _can_pause(self) -> bool:
        """Whether a run on this service can wait for an approval."""
        return self._persistence.checkpointer is not None and bool(self._tools().mutating())

    async def get_pending_approval(
        self,
        thread_id: str,
        *,
        user_id: str | None = None,
        principal: Principal | None = None,
    ) -> ApprovalRequiredResponse:
        """The approval a thread is waiting on, so a reloaded client can decide it.

        Read-only: it records no `approval_requested` event or metric (the run that paused
        did). A missing thread, another user's thread and a thread with nothing pending are the
        same `ApprovalNotFoundError`.
        """
        owner_key = self._owner_key(user_id, principal)
        bind_correlation_context(request_id=None, thread_id=thread_id)
        with self._persistence_errors():
            try:
                snapshot = await self._owned_snapshot(thread_id, owner_key)
            except ThreadNotFoundError:
                raise ApprovalNotFoundError("approval not found") from None
        interrupts = [i for task in snapshot.tasks for i in task.interrupts]
        if not interrupts:
            raise ApprovalNotFoundError("approval not found")
        approval = _approval_request(interrupts[0])
        audit(
            "approval_read",
            outcome="allowed",
            actor=owner_key[:12] if self._settings.auth_mode == "jwt" and owner_key else None,
            issuer_id=self._settings.auth_issuer_id,
            action="agent:approve",
            resource_type="approval",
            resource_id=approval.approval_id,
            count=len(approval.actions),
        )
        return ApprovalRequiredResponse(
            request_id=str(uuid.uuid4()), thread_id=thread_id, approval=approval
        )

    async def _pending_interrupts(self, thread_id: str) -> list[Interrupt]:
        snapshot = await self.graph.aget_state({"configurable": {"thread_id": thread_id}})
        return [interrupt for task in snapshot.tasks for interrupt in task.interrupts]

    def _approval_required(
        self, run: PreparedRun, interrupt: Interrupt
    ) -> ApprovalRequiredResponse:
        """The response for a run that paused, and the `approval_requested` audit event."""
        approval = _approval_request(interrupt)
        actions = approval.actions
        known = self._tools().names()
        self._record_approval("requested", len(actions))
        logger.info(
            "approval_requested",
            request_id=run.request_id,
            run_id=run.run_id,
            tool_names=[audit_tool_name(action.name, known) for action in actions],
        )
        audit(
            "approval_requested",
            outcome="allowed",
            actor=run.budget_key[:12] if self._settings.auth_mode == "jwt" else None,
            issuer_id=self._settings.auth_issuer_id,
            action="agent:invoke",
            resource_type="approval",
            resource_id=approval.approval_id,
            request_id=run.request_id,
            run_id=run.run_id,
            count=len(actions),
        )
        return ApprovalRequiredResponse(
            request_id=run.request_id, thread_id=run.thread_id, approval=approval
        )

    @staticmethod
    def _record_approval(decision: str, actions: int) -> None:
        """One span and one count for an approval request or decision: no arguments, no IDs."""
        with telemetry.start_span(
            semconv.APPROVAL_SPAN,
            attributes={
                semconv.NEURON_APPROVAL_DECISION: decision,
                semconv.NEURON_APPROVAL_ACTIONS: actions,
            },
        ):
            metrics.record_approval(decision)

    async def decide_approval(
        self,
        thread_id: str,
        approval_id: str,
        decision: Literal["approve", "reject"],
        *,
        user_id: str | None = None,
        principal: Principal | None = None,
        usage: TokenUsageAccumulator | None = None,
    ) -> AgentResponse | ApprovalRequiredResponse:
        """Decide a pending approval and continue the run (see `prepare_decision`)."""
        run = await self.prepare_decision(
            thread_id, approval_id, decision, user_id=user_id, principal=principal, usage=usage
        )
        return await self._execute(run)

    async def prepare_decision(
        self,
        thread_id: str,
        approval_id: str,
        decision: Literal["approve", "reject"],
        *,
        streaming: bool = False,
        user_id: str | None = None,
        principal: Principal | None = None,
        usage: TokenUsageAccumulator | None = None,
    ) -> PreparedRun:
        """Claim the run that continues a pending approval; nothing has executed yet.

        A new run, with its own lease, budget reservation and timeout. A missing, foreign or
        already-decided approval is the same `ApprovalNotFoundError`.
        """
        if self._refusing_new_runs():
            raise ShuttingDownError("server is shutting down")
        owner_key = self._owner_key(user_id, principal)
        request_id, run_id = str(uuid.uuid4()), str(uuid.uuid4())
        bind_correlation_context(request_id=request_id, thread_id=thread_id, run_id=run_id)
        # Cheap refusals first: nothing is reserved or claimed for an approval that isn't there.
        await self._matching_interrupt(thread_id, owner_key, approval_id)
        budget_key = owner_key or "anonymous"
        reservation = await self._reserve_budget(budget_key, self._settings.max_output_tokens)
        try:
            lease = self._count_in_flight(
                await self._claim(thread_id, streaming=streaming, owner_key=budget_key),
                reservation,
            )
        except BaseException:
            await self._token_budget.settle(reservation, 0)
            raise
        try:
            # Again, now that no other decision can run: a decision is single-use.
            pending = await self._matching_interrupt(thread_id, owner_key, approval_id)
        except BaseException:
            await lease.release()
            raise
        actions = len(pending.value["action_requests"])
        self._record_approval(decision, actions)
        audit(
            "approval_decided",
            outcome="allowed",
            actor=owner_key[:12] if self._settings.auth_mode == "jwt" and owner_key else None,
            issuer_id=self._settings.auth_issuer_id,
            action="agent:approve",
            resource_type="approval",
            resource_id=approval_id,
            request_id=request_id,
            run_id=run_id,
            reason=decision,
            count=actions,
        )
        return PreparedRun(
            request_id=request_id,
            thread_id=thread_id,
            run_id=run_id,
            graph_input=Command(resume={"decisions": [{"type": decision}] * actions}),
            authorization=self._authorization(owner_key, principal, usage),
            budget_key=budget_key,
            budget_reservation=reservation,
            checkpoint_owner=owner_key,
            created_thread=False,
            lease=lease,
        )

    async def _matching_interrupt(
        self, thread_id: str, owner_key: str | None, approval_id: str
    ) -> Interrupt:
        """The thread's pending interrupt with this ID, for its owner only."""
        with self._persistence_errors():
            try:
                snapshot = await self._owned_snapshot(thread_id, owner_key)
            except ThreadNotFoundError:
                raise ApprovalNotFoundError("approval not found") from None
        for task in snapshot.tasks:
            for interrupt in task.interrupts:
                if interrupt.id == approval_id:
                    return interrupt
        logger.info("approval_not_found")
        raise ApprovalNotFoundError("approval not found")

    def _authorization(
        self,
        owner_key: str | None,
        principal: Principal | None,
        usage: TokenUsageAccumulator | None,
    ) -> AuthorizationContext:
        """The run's trusted authorization inputs, from the verified principal only."""
        permissions = (
            DEV_PERMISSIONS | frozenset(spec.scope for spec in self._tools() if spec.scope)
            if self._settings.auth_mode == "none"
            else principal.scopes
            if principal is not None
            else frozenset()
        )
        return AuthorizationContext(
            permissions,
            principal,
            usage=usage or TokenUsageAccumulator(),
            actor=owner_key[:12] if self._settings.auth_mode == "jwt" and owner_key else None,
            issuer_id=self._settings.auth_issuer_id,
            owner_key=owner_key,
        )

    async def invoke(
        self,
        request: AgentRequest,
        *,
        principal: Principal | None = None,
        usage: TokenUsageAccumulator | None = None,
    ) -> AgentResponse | ApprovalRequiredResponse:
        """Run one turn. A caller-supplied `usage` accumulator receives the run's token counts."""
        run = await self.prepare(request, principal=principal, usage=usage)
        return await self._execute(run)

    async def _execute(self, run: PreparedRun) -> AgentResponse | ApprovalRequiredResponse:
        """Run a prepared run to its end or to a pause for approval, then settle and release."""
        try:
            with self._persistence_errors():
                async with asyncio.timeout(self._settings.run_timeout_seconds):
                    result = await self.graph.ainvoke(
                        run.graph_input, config=run.config, context=run.authorization
                    )
        except TimeoutError as exc:
            logger.warning("agent_run_timed_out")
            raise RunTimeoutError("agent run exceeded its time budget") from exc
        finally:
            try:
                await self._finish_usage(run)
            finally:
                await run.lease.release()
        # Checked first: after a pause the state still holds the previous turn's answer.
        response: AgentResponse | ApprovalRequiredResponse = (
            self._approval_required(run, interrupts[0])
            if (interrupts := result.get("__interrupt__"))
            else _response(run, result["answer"])
        )
        self._audit_thread_created(run)
        await self._name_new_thread(run)
        return response

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
        # Not made current here: a generator's context can change between `yield`s. The
        # producer task copies the context, so the run's spans become the stream span's children.
        span = telemetry.tracer().start_span(semconv.STREAM_SPAN)
        with trace.use_span(span):
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
            try:
                await self._finish_usage(run)
            finally:
                try:
                    await run.lease.release()
                finally:
                    stats.log()
                    stats.record_on(span)
                    span.end()

    async def _produce(self, run: PreparedRun, queue: asyncio.Queue[StreamEvent | None]) -> None:
        """Run the graph, translating its stream into events; always ends with `None`.

        The run budget is enforced here rather than by the consumer, so it holds even when
        the client stops reading and the generator is parked at a `yield`.
        """
        extractor = AnswerTokenExtractor()
        # Withholds text that could be a system prompt quote; the graph guards the final answer.
        guard = StreamLeakGuard()
        answer: AgentAnswer | None = None
        pending: Interrupt | None = None
        try:
            async with asyncio.timeout(self._settings.run_timeout_seconds):
                with self._persistence_errors():
                    async for namespace, mode, chunk in self.graph.astream(
                        run.graph_input,
                        config=run.config,
                        context=run.authorization,
                        stream_mode=["messages", "updates"],
                        # The create_agent loop runs as a nested graph inside the `agent`
                        # node; its model tokens are only surfaced with subgraphs enabled.
                        subgraphs=True,
                    ):
                        if mode == "updates" and not namespace and "__interrupt__" in chunk:
                            # A tool waits for a decision (ADR 0009): the run ends here.
                            pending = chunk["__interrupt__"][0]
                            continue
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
                        if delta := guard.feed(extractor.feed(message)):
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
            if pending is not None:
                # Text the guard still holds is the model's own, said before it asked for the tool.
                if tail := guard.flush():
                    queue.put_nowait(StreamEvent("token", {"text": tail}))
                self._audit_thread_created(run)
                await self._name_new_thread(run)
                paused = self._approval_required(run, pending)
                queue.put_nowait(StreamEvent("approval_required", paused.model_dump()))
            elif answer is None:
                logger.error("agent_stream_missing_answer")
                queue.put_nowait(
                    StreamEvent("error", {"code": "internal_server_error", "retryable": False})
                )
            else:
                if (tail := guard.flush()) and answer.answer != SYSTEM_PROMPT_REFUSAL:
                    queue.put_nowait(StreamEvent("token", {"text": tail}))
                self._audit_thread_created(run)
                await self._name_new_thread(run)
                queue.put_nowait(StreamEvent("final", _response(run, answer).model_dump()))
        finally:
            # Unbounded queue: its size is bounded by the run's own output
            # (APP_MAX_OUTPUT_TOKENS per model call, APP_MAX_AGENT_ITERATIONS calls).
            queue.put_nowait(None)

    async def _claim(self, thread_id: str, *, streaming: bool, owner_key: str) -> RunLease:
        """Claim the thread (reject-on-busy) and, for streams, a concurrency slot."""
        try:
            return await self._run_guard.claim(
                thread_id=thread_id,
                owner_key=owner_key,
                streaming=streaming,
                guard_thread=self._persistence.checkpointer is not None,
            )
        except RunClaimDenied as denied:
            raise self._denial(denied.reason, owner_key) from None

    def _count_in_flight(self, lease: RunLease, reservation: BudgetReservation) -> RunLease:
        """Count the run until its lease is released, for the `service_draining` log.

        Releasing the lease also gives back a token reservation nothing settled (a stream that
        never started); once `_finish_usage` has settled it, that is a no-op.
        """
        self._in_flight += 1

        async def release() -> None:
            try:
                await lease.release()
            finally:
                self._in_flight -= 1
                await self._token_budget.settle(reservation, 0)

        return RunLease(release)

    def _denial(self, reason: RunDenialReason, owner_key: str) -> AppError:
        """Record a refused claim and return the error to raise for it."""
        if reason == "thread_busy":
            logger.info("agent_thread_busy")
            return ThreadBusyError("a run is already in progress on this thread")
        metrics.record_policy_block(reason)
        if reason == "concurrent_streams":
            logger.warning(
                "agent_stream_capacity_exceeded", limit=self._settings.max_concurrent_streams
            )
        else:
            logger.warning(
                "user_limit_exceeded",
                limit_type="concurrent_runs",
                owner_key_prefix=owner_key[:12],
            )
        audit(
            "limit_exceeded",
            outcome="denied",
            actor=owner_key[:12] if self._settings.auth_mode == "jwt" else None,
            issuer_id=self._settings.auth_issuer_id,
            action="agent:invoke",
            resource_type="agent",
            reason=reason,
        )
        if reason == "concurrent_streams":
            return CapacityError("too many concurrent streams")
        return ConcurrentRunsExceededError("too many concurrent runs")

    async def _finish_usage(self, run: PreparedRun) -> None:
        usage = run.authorization.usage or TokenUsageAccumulator()
        # A run that reported no usage may still have spent tokens (cancelled, timed out, or a
        # provider that omits usage): keep the whole reservation rather than guess low.
        await self._token_budget.settle(
            run.budget_reservation, usage.total_tokens or run.budget_reservation.tokens
        )
        logger.info(
            "model_token_usage",
            request_id=run.request_id,
            run_id=run.run_id,
            owner_key_prefix=run.budget_key[:12],
            **usage.log_fields(),
        )

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

        Only `HumanMessage`/`AIMessage` turns are exposed. Tool calls appear as a name, a
        bounded argument summary and a status; system prompts and tool output never do.
        """
        owner_key = self._owner_key(user_id, principal)
        bind_correlation_context(request_id=None, thread_id=thread_id)
        with self._persistence_errors():
            snapshot = await self._owned_snapshot(thread_id, owner_key)
        turns = _public_thread_messages(
            snapshot.values.get("messages", []),
            with_tools=True,
            awaiting_decision=any(task.interrupts for task in snapshot.tasks),
        )
        response = ThreadHistoryResponse(
            thread_id=thread_id,
            messages=turns[offset : offset + limit],
            total=len(turns),
            limit=limit,
            offset=offset,
        )
        audit(
            "thread_read",
            outcome="allowed",
            actor=owner_key[:12] if self._settings.auth_mode == "jwt" and owner_key else None,
            issuer_id=self._settings.auth_issuer_id,
            action="threads:read",
            resource_type="thread",
            resource_id=thread_id,
        )
        return response

    async def rename_thread(
        self,
        thread_id: str,
        title: str,
        user_id: str | None,
        *,
        principal: Principal | None = None,
    ) -> ThreadTitleResponse:
        """Set an owned thread's title; another user's or a missing thread is the same `404`."""
        owner_key = self._owner_key(user_id, principal)
        bind_correlation_context(request_id=None, thread_id=thread_id)
        with self._persistence_errors():
            await self._owned_thread_state(thread_id, owner_key)
            if owner_key is None:  # an anonymous thread is not listed, so it has no title
                raise ThreadNotFoundError("thread not found")
            await self._persistence.thread_titles.rename(owner_key, thread_id, title)
        audit(
            "thread_renamed",
            outcome="allowed",
            actor=owner_key[:12] if self._settings.auth_mode == "jwt" else None,
            issuer_id=self._settings.auth_issuer_id,
            action="threads:write",
            resource_type="thread",
            resource_id=thread_id,
        )
        return ThreadTitleResponse(thread_id=thread_id, title=title)

    async def submit_feedback(
        self,
        thread_id: str,
        run_id: str,
        score: int,
        reason: str | None,
        user_id: str | None,
        *,
        principal: Principal | None = None,
    ) -> FeedbackResponse:
        """Record the caller's rating of one answer; the first rating of a run stands.

        A missing thread and another user's thread are the same `404`. The `run_id` is not
        checked against the thread's history (an old run's ID is not kept there): it only keys
        the caller's own rating, and a run ID already rated on another thread is refused.
        """
        owner_key = self._owner_key(user_id, principal)
        bind_correlation_context(request_id=None, thread_id=thread_id, run_id=run_id)
        with self._persistence_errors():
            await self._owned_thread_state(thread_id, owner_key)
            if owner_key is None:  # an anonymous thread has no owner to file a rating under
                raise ThreadNotFoundError("thread not found")
            stored = await self._persistence.feedback.record(
                owner_key, thread_id, run_id, score, reason
            )
        if stored.thread_id != thread_id:
            raise ThreadNotFoundError("thread not found")
        if stored.created:
            label = "up" if stored.score > 0 else "down"
            with telemetry.start_span(
                semconv.FEEDBACK_SPAN,
                attributes={
                    semconv.NEURON_FEEDBACK_SCORE: label,
                    semconv.NEURON_FEEDBACK_REASON: stored.reason or "none",
                },
            ):
                metrics.record_feedback(label, stored.reason or "none")
            logger.info("user_feedback", score=label, reason=stored.reason or "none")
            audit(
                "feedback_recorded",
                outcome="allowed",
                actor=owner_key[:12] if self._settings.auth_mode == "jwt" else None,
                issuer_id=self._settings.auth_issuer_id,
                action="feedback:write",
                resource_type="run",
                resource_id=run_id,
                reason=stored.reason,
            )
        return FeedbackResponse(run_id=run_id, score=stored.score, reason=stored.reason)

    async def list_user_threads(
        self,
        user_id: str | None,
        *,
        limit: int,
        offset: int,
        principal: Principal | None = None,
    ) -> UserThreadsResponse:
        """List only the caller's threads, newest activity first, without content.

        Only the returned page's latest checkpoints are read, to count their messages.
        """
        owner_key = self._owner_key(user_id, principal)
        summaries: list[UserThreadSummary] = []
        with self._persistence_errors():
            page = await self._owned_threads(owner_key, limit=limit, offset=offset)
            titles = await self._titles_of(owner_key, page)
            for thread in page.threads:
                messages = await self._latest_public_messages(thread.thread_id, owner_key)
                if messages is None:
                    continue
                summaries.append(
                    UserThreadSummary(
                        thread_id=thread.thread_id,
                        created_at=thread.created_at,
                        updated_at=thread.updated_at,
                        message_count=len(messages),
                        title=titles.get(thread.thread_id),
                    )
                )
        return UserThreadsResponse(threads=summaries, total=page.total, limit=limit, offset=offset)

    async def export_user_data(
        self,
        user_id: str | None,
        *,
        limit: int,
        offset: int,
        message_limit: int,
        message_offset: int,
        principal: Principal | None = None,
    ) -> UserDataExportResponse:
        """Export owner-scoped public turns with independent thread/message pagination.

        Threads are read one at a time, stopping as soon as the export exceeds its cap.
        """
        owner_key = self._owner_key(user_id, principal)
        max_bytes = self._settings.user_data_export_max_bytes
        exported: list[ExportedThread] = []
        has_more_messages = False
        exported_bytes = 0
        with self._persistence_errors():
            page = await self._owned_threads(owner_key, limit=limit, offset=offset)
            titles = await self._titles_of(owner_key, page)
            for thread in page.threads:
                messages = await self._latest_public_messages(thread.thread_id, owner_key)
                if messages is None:
                    continue
                item = ExportedThread(
                    title=titles.get(thread.thread_id),
                    thread_id=thread.thread_id,
                    created_at=thread.created_at,
                    updated_at=thread.updated_at,
                    message_total=len(messages),
                    messages=messages[message_offset : message_offset + message_limit],
                )
                exported_bytes += len(item.model_dump_json().encode("utf-8"))
                if exported_bytes > max_bytes:
                    raise ExportTooLargeError("reduce the thread or message page size and retry")
                exported.append(item)
                has_more_messages |= message_offset + message_limit < len(messages)
        memories = (
            [_memory_item(m) for m in await self._memory.list(owner_key)]
            if self._memory is not None and offset == 0
            else []
        )
        response = UserDataExportResponse(
            threads=exported,
            total_threads=page.total,
            limit=limit,
            offset=offset,
            message_limit=message_limit,
            message_offset=message_offset,
            has_more_messages=has_more_messages,
            memories=memories,
        )
        if len(response.model_dump_json().encode("utf-8")) > max_bytes:
            raise ExportTooLargeError("reduce the thread or message page size and retry")
        audit(
            "user_data_exported",
            outcome="allowed",
            actor=(
                owner_key[:12]
                if self._settings.auth_mode == "jwt" and owner_key is not None
                else None
            ),
            issuer_id=self._settings.auth_issuer_id,
            action="threads:export",
            resource_type="user_data",
            count=len(exported),
        )
        return response

    @property
    def memory(self) -> MemoryStore | None:
        """The per-user memory, or None while memory is off."""
        return self._memory

    def owner_key_for(self, principal: Principal) -> str | None:
        """The owner key a verified principal's data is filed under."""
        return self._owner_key(None, principal)

    def _require_memory(self) -> MemoryStore:
        if self._memory is None:
            raise MemoryDisabledError("memory is not enabled")
        return self._memory

    def _audit_memory(
        self,
        event: str,
        owner_key: str | None,
        *,
        action: str,
        count: int | None = None,
        resource_id: str | None = None,
    ) -> None:
        audit(
            event,
            outcome="allowed",
            actor=owner_key[:12] if self._settings.auth_mode == "jwt" and owner_key else None,
            issuer_id=self._settings.auth_issuer_id,
            action=action,
            resource_type="memory",
            resource_id=resource_id,
            count=count,
        )

    async def list_memories(
        self,
        user_id: str | None,
        *,
        limit: int,
        offset: int,
        principal: Principal | None = None,
    ) -> MemoriesResponse:
        """A page of the caller's own memories, oldest first."""
        memory = self._require_memory()
        owner_key = self._owner_key(user_id, principal)
        with self._persistence_errors():
            found = await memory.list(owner_key)
        self._audit_memory("memories_read", owner_key, action="memories:read", count=len(found))
        return MemoriesResponse(
            memories=[_memory_item(m) for m in found[offset : offset + limit]],
            total=len(found),
            limit=limit,
            offset=offset,
        )

    async def forget_memory(
        self, memory_id: str, user_id: str | None, *, principal: Principal | None = None
    ) -> None:
        """Delete one of the caller's memories; another user's ID is the same `404`."""
        memory = self._require_memory()
        owner_key = self._owner_key(user_id, principal)
        with self._persistence_errors():
            deleted = await memory.forget(owner_key, memory_id)
        if not deleted:
            raise MemoryNotFoundError("memory not found")
        self._audit_memory(
            "memory_deleted", owner_key, action="memories:write", resource_id=memory_id
        )

    async def erase_memories(
        self, user_id: str | None, *, principal: Principal | None = None
    ) -> MemoryErasureResponse:
        """Delete all of the caller's memories."""
        memory = self._require_memory()
        owner_key = self._owner_key(user_id, principal)
        with self._persistence_errors():
            erased = await memory.erase(owner_key)
        self._audit_memory("memories_erased", owner_key, action="memories:write", count=erased)
        return MemoryErasureResponse(erased_count=erased)

    async def erase_user_data(
        self, user_id: str | None, *, principal: Principal | None = None
    ) -> UserDataErasureResponse:
        """Delete all discoverable owned threads, skipping active runs idempotently."""
        owner_key = self._owner_key(user_id, principal)
        erased = 0
        erased_memories = 0
        skipped_busy = 0
        failed = True
        try:
            active_owned = (
                await self._run_guard.active_threads_of(owner_key)
                if owner_key is not None
                else frozenset[str]()
            )
            checkpointer = self._persistence.checkpointer
            if checkpointer is not None:
                with self._persistence_errors():
                    page = await self._owned_threads(owner_key, limit=None)
                    for thread in page.threads:
                        thread_id = thread.thread_id
                        if thread_id in active_owned:
                            skipped_busy += 1
                            continue
                        # Held while it is deleted, so no run can start on it meanwhile.
                        try:
                            lease = await self._run_guard.hold_thread(
                                thread_id=thread_id, owner_key=owner_key or "anonymous"
                            )
                        except RunClaimDenied:
                            skipped_busy += 1  # a run started after the listing
                            continue
                        try:
                            await checkpointer.adelete_thread(thread_id)
                            await self._forget_thread_content([thread_id])
                        finally:
                            await lease.release()
                        erased += 1
                    if skipped_busy == 0 and owner_key is not None:
                        await self._forget_owner_content(owner_key)
            if self._memory is not None:
                with self._persistence_errors():
                    erased_memories = await self._memory.erase(owner_key)
                self._audit_memory(
                    "memories_erased", owner_key, action="threads:erase_all", count=erased_memories
                )
            failed = False
        finally:
            # Also when it stops part-way: the count so far, never thread IDs.
            audit(
                "user_data_erased",
                outcome="error" if failed else "allowed",
                actor=(
                    owner_key[:12]
                    if self._settings.auth_mode == "jwt" and owner_key is not None
                    else None
                ),
                issuer_id=self._settings.auth_issuer_id,
                action="threads:erase_all",
                resource_type="user_data",
                count=erased,
                reason="erasure_failed"
                if failed
                else "busy_threads_skipped"
                if skipped_busy
                else None,
            )
        return UserDataErasureResponse(
            erased_count=erased,
            skipped_busy_count=skipped_busy,
            erased_memory_count=erased_memories,
        )

    async def _forget_thread_content(self, thread_ids: list[str]) -> None:
        """Remove what is kept beside a deleted thread: its title and the ratings of its runs."""
        await self._persistence.thread_titles.forget_threads(thread_ids)
        await self._persistence.feedback.forget_threads(thread_ids)

    async def _forget_owner_content(self, owner_key: str) -> None:
        await self._persistence.thread_titles.forget_owner(owner_key)
        await self._persistence.feedback.forget_owner(owner_key)

    async def _titles_of(self, owner_key: str | None, page: OwnedThreadPage) -> dict[str, str]:
        if owner_key is None:
            return {}
        return await self._persistence.thread_titles.titles(
            owner_key, [thread.thread_id for thread in page.threads]
        )

    async def _owned_threads(
        self, owner_key: str | None, *, limit: int | None, offset: int = 0
    ) -> OwnedThreadPage:
        if owner_key is None:
            return OwnedThreadPage(total=0, threads=[])
        return await owned_threads(self._persistence, owner_key, limit=limit, offset=offset)

    async def _latest_public_messages(
        self, thread_id: str, owner_key: str | None
    ) -> list[ThreadMessage] | None:
        """The public turns of an owned thread's latest checkpoint; None if it's gone."""
        checkpointer = self._persistence.checkpointer
        if checkpointer is None:
            return None
        item = await checkpointer.aget_tuple(
            {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
        )
        if item is None or item.metadata.get("owner") != owner_key:
            return None
        channels = item.checkpoint.get("channel_values", {})
        raw_messages = channels.get("messages", []) if isinstance(channels, dict) else []
        return _public_thread_messages(raw_messages)

    async def delete_thread(
        self, thread_id: str, user_id: str | None, *, principal: Principal | None = None
    ) -> None:
        """Delete every checkpoint of an owned thread. Rejected while a run is in flight."""
        owner_key = self._owner_key(user_id, principal)
        bind_correlation_context(request_id=None, thread_id=thread_id)
        with self._persistence_errors():
            await self._owned_thread_state(thread_id, owner_key)
            try:
                # The in-flight run would re-create the thread with its final write, and a
                # run starting mid-delete would lose its history; the hold prevents both.
                lease = await self._run_guard.hold_thread(
                    thread_id=thread_id, owner_key=owner_key or "anonymous"
                )
            except RunClaimDenied:
                logger.info("agent_thread_busy")
                raise ThreadBusyError("a run is already in progress on this thread") from None
            try:
                checkpointer = self._persistence.checkpointer
                # _owned_thread_state already raised if there is no checkpointer.
                assert checkpointer is not None  # nosec B101
                await checkpointer.adelete_thread(thread_id)
                await self._forget_thread_content([thread_id])
            finally:
                await lease.release()
        audit(
            "thread_deleted",
            outcome="allowed",
            actor=owner_key[:12] if self._settings.auth_mode == "jwt" and owner_key else None,
            issuer_id=self._settings.auth_issuer_id,
            action="threads:delete",
            resource_type="thread",
            resource_id=thread_id,
        )

    async def _owned_thread_state(self, thread_id: str, owner_key: str | None) -> dict[str, Any]:
        """Return the thread's state if it exists and belongs to the effective owner.

        A missing thread, another user's thread, and a service without persistence all raise
        the same `ThreadNotFoundError`, so thread IDs cannot be probed.
        """
        values: dict[str, Any] = (await self._owned_snapshot(thread_id, owner_key)).values
        return values

    async def _owned_snapshot(self, thread_id: str, owner_key: str | None) -> StateSnapshot:
        """`_owned_thread_state` with the whole snapshot (state and pending tasks)."""
        if self._persistence.checkpointer is None:
            raise ThreadNotFoundError("thread not found")
        snapshot = await self.graph.aget_state({"configurable": {"thread_id": thread_id}})
        owner_field = "owner_key" if self._settings.auth_mode == "jwt" else "user_id_hash"
        if not snapshot.values or snapshot.values.get(owner_field) != owner_key:
            logger.info("thread_access_denied")
            audit(
                "authorization_denied",
                outcome="denied",
                actor=owner_key[:12] if self._settings.auth_mode == "jwt" and owner_key else None,
                issuer_id=self._settings.auth_issuer_id,
                action="threads:access",
                resource_type="thread",
                resource_id=thread_id,
                reason="thread_not_found",
            )
            raise ThreadNotFoundError("thread not found")
        return snapshot  # type: ignore[no-any-return]

    def _owner_key(self, user_id: str | None, principal: Principal | None) -> str | None:
        """Resolve the owner without allowing request identity to override JWT identity."""
        if self._settings.auth_mode == "jwt":
            if principal is None or self._settings.identity_hash_key is None:
                raise AuthenticationError("authenticated principal is required")
            return principal_owner_key(
                principal, self._settings.identity_hash_key.get_secret_value()
            )
        return _hash_identifier(user_id) if user_id else None


def _approval_request(interrupt: Interrupt) -> ApprovalRequest:
    """What the caller is asked to decide, from the interrupt a run paused on."""
    actions = [
        PendingAction(name=str(action["name"]), args=dict(action["args"]))
        for action in interrupt.value["action_requests"]
    ]
    return ApprovalRequest(
        approval_id=interrupt.id, actions=actions, allowed_decisions=["approve", "reject"]
    )


def _response(run: PreparedRun, answer: AgentAnswer) -> AgentResponse:
    return AgentResponse(
        request_id=run.request_id,
        thread_id=run.thread_id,
        answer=answer.answer,
        used_tools=answer.used_tools,
        confidence=answer.confidence,
        refused=answer.refused,
        clarification_needed=answer.clarification_needed,
    )


def _memory_item(memory: Memory) -> MemoryItem:
    return MemoryItem(id=memory.id, text=memory.text, created_at=memory.created_at)


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
        elif event.event == "approval_required":
            self.termination = "approval_required"
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
        log = (
            logger.info
            if self.termination in {"completed", "approval_required"}
            else logger.warning
        )
        log("stream_completed", termination=self.termination, error_code=self.error_code, **fields)

    def record_on(self, span: Span) -> None:
        """Set the stream span's time to first token, event count and termination."""
        termination = (self.termination or "error") if self.finished else "client_disconnect"
        span.set_attribute(semconv.NEURON_STREAM_EVENTS, self.events)
        span.set_attribute(semconv.NEURON_STREAM_TERMINATION, termination)
        if self.first_token_ms is not None:
            span.set_attribute(semconv.NEURON_STREAM_TTFT_MS, self.first_token_ms)
            metrics.record_stream_ttft(self.first_token_ms / 1000, outcome=termination)
        if self.error_code is not None:
            telemetry.record_error(span, self.error_code)
            metrics.record_error(self.error_code)

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


def _public_thread_messages(
    messages: Any, *, with_tools: bool = False, awaiting_decision: bool = False
) -> list[ThreadMessage]:
    """The history API's safe projection: user and assistant turns, optionally with tool calls.

    A tool call has no result message while it waits for an approval (`awaiting_decision`);
    without one and without a pending decision it never completed.
    """
    if not isinstance(messages, list):
        return []
    results = {m.tool_call_id: m for m in messages if isinstance(m, ToolMessage)}
    turns: list[ThreadMessage] = []
    for message in messages:
        if not isinstance(message, HumanMessage | AIMessage):
            continue
        text = message.content if isinstance(message.content, str) else ""
        calls = (
            [
                _tool_call_record(call, results.get(str(call.get("id"))), awaiting_decision)
                for call in message.tool_calls
            ]
            if with_tools and isinstance(message, AIMessage)
            else []
        )
        if text or calls:
            role = "user" if isinstance(message, HumanMessage) else "assistant"
            turns.append(ThreadMessage(role=role, content=text, tool_calls=calls))
    return turns


_SUMMARY_VALUE_CHARS = 60
_SUMMARY_CHARS = 200
_REJECTED_PREFIX = "User rejected the tool call"


def _tool_call_record(
    call: Mapping[str, Any], result: ToolMessage | None, awaiting_decision: bool
) -> ToolCallRecord:
    """Server-rendered, length-bounded view of one tool call. The tool's output is used only
    for its status; a rejection is recognised by the approval middleware's fixed prefix."""
    args = call.get("args")
    parts = [
        f"{key}={' '.join(str(value).split())[:_SUMMARY_VALUE_CHARS]}"
        for key, value in (args.items() if isinstance(args, dict) else [])
    ]
    status: Literal["pending", "completed", "failed", "rejected"]
    if result is None:
        status = "pending" if awaiting_decision else "failed"
    elif result.status != "error":
        status = "completed"
    elif isinstance(result.content, str) and result.content.startswith(_REJECTED_PREFIX):
        status = "rejected"
    else:
        status = "failed"
    return ToolCallRecord(
        name=str(call.get("name", ""))[:64],
        summary=", ".join(parts)[:_SUMMARY_CHARS],
        status=status,
    )
