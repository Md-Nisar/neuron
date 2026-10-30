"""Shared token budget in Postgres (#147, ADR 0008 decision 8), against a real database.

Budget-level tests use `PostgresTokenBudget` directly (two pools are two replicas);
service-level tests run an `AgentService` on a database; the HTTP tests run two Uvicorn
processes (`pg_harness.py`).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
import structlog.testing
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from pg_harness import AppProcess
from psycopg.conninfo import make_conninfo
from pydantic import SecretStr

from neuron_agent.config.settings import Settings
from neuron_agent.errors.base import PersistenceError, QuotaExceededError, RunTimeoutError
from neuron_agent.graphs import main_graph
from neuron_agent.observability import metrics, semconv
from neuron_agent.persistence.checkpointer import build_persistence
from neuron_agent.persistence.retention import prune_threads
from neuron_agent.persistence.token_budget import PostgresTokenBudget
from neuron_agent.schemas.agent import AgentAnswer, AgentRequest
from neuron_agent.security.usage_budget import (
    BudgetDecision,
    BudgetReservation,
    InMemoryRollingTokenBudget,
    TokenBudget,
)
from neuron_agent.services.agent_service import AgentService

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.anyio]


# --- helpers ---------------------------------------------------------------------------


async def rows(dsn: str, query: str, *params: object) -> list[tuple[Any, ...]]:
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as conn:
        cursor = await conn.execute(query, params)  # type: ignore[call-overload]
        return await cursor.fetchall() if cursor.description else []


async def total(dsn: str, owner: str | None = None) -> int:
    query = "SELECT coalesce(sum(tokens), 0) FROM neuron_token_ledger"
    if owner is None:
        return int((await rows(dsn, query))[0][0])
    return int((await rows(dsn, query + " WHERE owner_key = %s", owner))[0][0])


async def eventually(check: Callable[[], Awaitable[bool]], *, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while not await check():
        assert time.monotonic() < deadline, "condition not reached in time"
        await asyncio.sleep(0.05)


def _settings(dsn: str, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "env": "test",
        "checkpointer": "none",
        "limits_backend": "postgres",
        "postgres_dsn": SecretStr(dsn),
        "max_concurrent_runs_per_user": 100,
        "openai_api_key": None,
    }
    return Settings(**{**values, **overrides})


@asynccontextmanager
async def budget_on(
    dsn: str, *, limit: int = 100, window: int = 3600, lock_timeout_ms: int = 2_000
) -> AsyncIterator[PostgresTokenBudget]:
    """A budget on its own pool; two of these are two replicas."""
    persistence = build_persistence(_settings(dsn))
    await persistence.open()
    assert persistence.pool is not None
    try:
        yield PostgresTokenBudget(
            persistence.pool,
            token_limit=limit,
            window_seconds=window,
            lock_timeout_ms=lock_timeout_ms,
        )
    finally:
        await persistence.close()


async def _admit(budget: TokenBudget, key: str, tokens: int) -> BudgetReservation:
    decision = await budget.reserve(key, tokens)
    assert decision.allowed and decision.reservation is not None
    return decision.reservation


# --- the existing budget scenarios, on both implementations -----------------------------


@pytest.fixture(params=["memory", "postgres"])
async def any_budget(request: pytest.FixtureRequest, database: str) -> AsyncIterator[TokenBudget]:
    if request.param == "memory":
        yield InMemoryRollingTokenBudget(token_limit=100, window_seconds=3600)
        return
    async with budget_on(database) as budget:
        yield budget


async def test_reserve_settle_and_refuse_on_both_implementations(any_budget: TokenBudget) -> None:
    first = await _admit(any_budget, "a", 60)
    refused = await any_budget.reserve("a", 60)  # 60 + 60 > 100
    assert (refused.allowed, refused.reservation) == (False, None)
    assert 1 <= refused.retry_after_seconds <= 3600 + 60
    assert (await any_budget.reserve("b", 60)).allowed is True  # another owner is unaffected

    await any_budget.settle(first, 10)
    await any_budget.settle(first, 99)  # idempotent
    second = await _admit(any_budget, "a", 60)  # 10 + 60 fits
    await any_budget.settle(second, 0)
    assert (await any_budget.reserve("a", 90)).allowed is True
    capped = await any_budget.reserve("c", 5_000)  # a reservation never exceeds the budget
    assert capped.reservation is not None and capped.reservation.tokens == 100


async def test_usage_charged_on_one_replica_is_refused_on_the_other(database: str) -> None:
    async with budget_on(database) as one, budget_on(database) as two:
        await one.settle(await _admit(one, "a", 100), 100)
        denied = await two.reserve("a", 1)
        assert denied.allowed is False and denied.retry_after_seconds > 0

    # The same scenario with the in-memory budget: each replica grants the full budget.
    mem_one = InMemoryRollingTokenBudget(token_limit=100, window_seconds=3600)
    mem_two = InMemoryRollingTokenBudget(token_limit=100, window_seconds=3600)
    await mem_one.settle(await _admit(mem_one, "a", 100), 100)
    assert (await mem_two.reserve("a", 1)).allowed is True


async def test_usage_survives_a_restart(database: str) -> None:
    async with budget_on(database) as before:
        await before.settle(await _admit(before, "a", 70), 70)
    async with budget_on(database) as after:  # a new pool: a restarted process
        assert (await after.reserve("a", 40)).allowed is False
        assert (await after.reserve("a", 30)).allowed is True


# --- atomicity ---------------------------------------------------------------------------


async def test_barrier_concurrent_admissions_never_exceed_the_budget(database: str) -> None:
    async with budget_on(database, limit=100) as one, budget_on(database, limit=100) as two:
        decisions: list[BudgetDecision] = await asyncio.gather(
            *([one, two][i % 2].reserve("same-owner", 30) for i in range(60))
        )
        assert sum(d.allowed for d in decisions) == 3  # 3 * 30 <= 100 < 4 * 30
        assert await total(database) == 90
        other = await asyncio.gather(*(one.reserve(f"o{i}", 100) for i in range(5)))
        assert all(d.allowed for d in other)  # owners do not share a budget


async def test_concurrent_settlements_sum_exactly(database: str) -> None:
    async with (
        budget_on(database, limit=1_000_000) as one,
        budget_on(database, limit=1_000_000) as two,
    ):
        reservations = [await _admit([one, two][i % 2], "a", 1) for i in range(100)]
        assert await total(database) == 100
        extra = [3 if i % 2 else 0 for i in range(100)]  # half use 3 tokens, half give theirs back
        await asyncio.gather(
            *([one, two][i % 2].settle(r, extra[i]) for i, r in enumerate(reservations))
        )
        assert await total(database) == 3 * 50


# --- window, granularity, retry-after -----------------------------------------------------


async def test_window_has_one_minute_granularity_and_retry_after_counts_to_its_end(
    database: str,
) -> None:
    async with budget_on(database, limit=100, window=300) as budget:
        await budget.settle(await _admit(budget, "a", 100), 100)
        denied = await budget.reserve("a", 1)
        # The charge is held until the end of its minute plus the 300 s window: 300 to 360 s.
        assert 300 <= denied.retry_after_seconds <= 360

        # Move the minute back to just inside, then just outside, `window + 60 s` ago.
        move = (
            "UPDATE neuron_token_ledger SET minute = date_trunc('minute', clock_timestamp()) - %s"
        )
        await rows(database, move, timedelta(seconds=300))  # ends 240 s ago + 300 s window: in
        assert (await budget.reserve("a", 1)).allowed is False
        await rows(database, move, timedelta(seconds=360))  # ended 300 s ago: out
        assert (await budget.reserve("a", 100)).allowed is True


async def test_retry_after_waits_only_until_enough_usage_leaves(database: str) -> None:
    async with budget_on(database, limit=100, window=3600) as budget:
        await rows(
            database,
            "INSERT INTO neuron_token_ledger (owner_key, minute, tokens) VALUES"
            " ('a', date_trunc('minute', clock_timestamp()) - interval '50 minutes', 40),"
            " ('a', date_trunc('minute', clock_timestamp()) - interval '10 minutes', 60)",
        )
        denied = await budget.reserve("a", 30)
        # Dropping the 50-minute-old 40 tokens is enough: 10 minutes (+ the rest of its minute).
        assert 600 <= denied.retry_after_seconds <= 660


async def test_settling_less_never_makes_the_ledger_negative(database: str) -> None:
    async with budget_on(database) as budget:
        held = await _admit(budget, "a", 50)
        await rows(database, "UPDATE neuron_token_ledger SET tokens = 10")  # others settled
        await budget.settle(held, 0)
        assert await total(database) == 0


async def test_the_retention_job_deletes_minutes_outside_the_window(database: str) -> None:
    await rows(
        database,
        "INSERT INTO neuron_token_ledger (owner_key, minute, tokens) VALUES"
        " ('a', date_trunc('minute', clock_timestamp()), 5),"
        " ('a', date_trunc('minute', clock_timestamp()) - interval '1 minute', 6),"
        " ('a', date_trunc('minute', clock_timestamp()) - interval '2 hours', 7)",
    )
    persistence = build_persistence(_settings(database))
    await persistence.open()
    try:
        await prune_threads(
            persistence, older_than=timedelta(days=365), ledger_window_seconds=60
        )  # keeps what a 60 s window plus its minute still counts
    finally:
        await persistence.close()
    assert sorted(r[0] for r in await rows(database, "SELECT tokens FROM neuron_token_ledger")) == [
        5,
        6,
    ]


# --- services: settle on every path ------------------------------------------------------


class UsageAgent:
    """Stands in for the model; `mode` selects how a run ends after it reports `usage`."""

    def __init__(self) -> None:
        self.calls = 0
        self.usage: int | None = None
        self.mode = "answer"
        self.started = asyncio.Event()
        self.before_answer: Callable[[], Awaitable[None]] | None = None

    async def ainvoke(self, inputs: dict[str, Any], context: Any, **_: Any) -> dict[str, Any]:
        self.calls += 1
        if self.usage is not None:
            context.usage.record({"total_tokens": self.usage})
        self.started.set()
        if self.mode == "hang":
            await asyncio.Event().wait()
        if self.mode == "fail":
            raise RuntimeError("model unavailable")
        if self.before_answer is not None:
            await self.before_answer()
        answer = AgentAnswer(answer="ok", used_tools=[], confidence=1.0)
        return {"messages": [], "structured_response": answer}


@asynccontextmanager
async def replica(
    dsn: str, monkeypatch: pytest.MonkeyPatch, agent: UsageAgent, **settings: Any
) -> AsyncIterator[AgentService]:
    lock_timeout_ms = settings.pop("lock_timeout_ms", 2_000)
    resolved = _settings(dsn, user_token_budget=1_000, max_output_tokens=100, **settings)
    monkeypatch.setattr(main_graph, "build_agent", lambda s: agent)
    persistence = build_persistence(resolved)
    assert persistence.pool is not None
    budget = PostgresTokenBudget(
        persistence.pool,
        token_limit=resolved.user_token_budget,
        window_seconds=resolved.user_token_budget_window_seconds,
        lock_timeout_ms=lock_timeout_ms,
    )
    service = AgentService(resolved, persistence=persistence, token_budget=budget)
    await service.startup()
    try:
        yield service
    finally:
        await service.shutdown()


async def _settled(dsn: str, expected: int) -> None:
    async def check() -> bool:
        return await total(dsn) == expected

    await eventually(check)


async def test_usage_is_charged_on_success_failure_timeout_cancellation_and_disconnect(
    database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = UsageAgent()
    async with replica(database, monkeypatch, agent, run_timeout_seconds=1) as service:
        agent.usage = 11
        await service.invoke(AgentRequest(message="success"))
        await _settled(database, 11)

        agent.usage, agent.mode = 7, "fail"
        with pytest.raises(Exception, match="agent"):
            await service.invoke(AgentRequest(message="failure"))
        await _settled(database, 18)

        agent.usage, agent.mode = 5, "hang"
        with pytest.raises(RunTimeoutError):
            await service.invoke(AgentRequest(message="timeout"))
        await _settled(database, 23)  # the partial usage, not the reservation

        agent.usage, agent.mode = 3, "hang"
        agent.started.clear()
        cancelled = asyncio.create_task(service.invoke(AgentRequest(message="cancelled")))
        await agent.started.wait()
        assert await total(database) > 23  # the reservation is held while the run is live
        cancelled.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled
        await _settled(database, 26)

        agent.usage, agent.mode = 2, "hang"
        agent.started.clear()
        run = await service.prepare(AgentRequest(message="stream"), streaming=True)
        stream = service.stream(run)
        assert (await anext(stream)).event == "run_started"
        pending = asyncio.ensure_future(anext(stream))
        await agent.started.wait()
        pending.cancel()  # the client went away
        with pytest.raises(asyncio.CancelledError):
            await pending
        await stream.aclose()
        await _settled(database, 28)


async def test_a_run_without_usage_keeps_its_whole_reservation(
    database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = UsageAgent()
    async with replica(database, monkeypatch, agent) as service:
        await service.invoke(AgentRequest(message="x" * 30))  # 100 + the estimate 10
        await _settled(database, 110)


async def test_a_cancelled_run_without_usage_keeps_its_whole_reservation(
    database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = UsageAgent()
    agent.mode = "hang"
    async with replica(database, monkeypatch, agent) as service:
        run = asyncio.create_task(service.invoke(AgentRequest(message="x" * 30)))
        await agent.started.wait()
        run.cancel()
        with pytest.raises(asyncio.CancelledError):
            await run
        await _settled(database, 110)


async def test_a_settlement_replayed_after_an_ambiguous_commit_applies_once(
    database: str,
) -> None:
    async with budget_on(database, limit=1_000) as budget:
        held = await _admit(budget, "a", 100)
        real = budget._write

        async def commit_then_lose_the_reply(reservation: BudgetReservation, actual: int) -> None:
            await real(reservation, actual)  # committed ...
            raise psycopg.OperationalError("connection lost")  # ... but the caller never learns

        budget._write = commit_then_lose_the_reply  # type: ignore[method-assign]
        await budget.settle(held, 30)  # fails as far as the budget can tell: kept for retry
        assert await total(database) == 30
        assert budget._unsettled["a"]

        budget._write = real  # type: ignore[method-assign]
        decision = await budget.reserve("a", 10)  # retries the settlement first
        assert decision.allowed
        assert await total(database) == 40  # 30 + the new 10; the 70 was not subtracted twice
        assert "a" not in budget._unsettled
        assert await total(database, "a") == 40


async def test_one_owner_cannot_hold_more_pool_connections_than_its_gate(database: str) -> None:
    class CountingPool:
        def __init__(self, pool: Any) -> None:
            self.pool, self.now, self.peak = pool, 0, 0

        @asynccontextmanager
        async def connection(self) -> AsyncIterator[Any]:
            self.now += 1
            self.peak = max(self.peak, self.now)
            try:
                async with self.pool.connection() as conn:
                    yield conn
            finally:
                self.now -= 1

    persistence = build_persistence(_settings(database))
    await persistence.open()
    assert persistence.pool is not None
    counting = CountingPool(persistence.pool)
    budget = PostgresTokenBudget(
        counting,  # type: ignore[arg-type]
        token_limit=1_000_000,
        window_seconds=3600,
        lock_timeout_ms=2_000,
        max_concurrent_reserves_per_owner=2,
    )
    try:
        lock = "SELECT pg_advisory_xact_lock(hashtextextended('neuron.token_budget:burst', 0))"
        async with await psycopg.AsyncConnection.connect(database) as holder:
            await holder.execute(lock)  # every reserve of this owner parks on the owner lock
            results = await asyncio.gather(
                *(budget.reserve("burst", 1) for _ in range(12)), return_exceptions=True
            )
            assert all(isinstance(r, PersistenceError) for r in results)
        assert counting.peak <= 2
        assert budget._gates == {}  # nothing is kept for an owner with no reserve in flight
        assert (await budget.reserve("burst", 1)).allowed
    finally:
        await persistence.close()


async def test_a_run_that_never_started_gives_its_reservation_back(
    database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = UsageAgent()
    async with replica(database, monkeypatch, agent) as service:
        run = await service.prepare(AgentRequest(message="x" * 30), streaming=True)
        assert await total(database) == 110  # max_output_tokens 100 + the estimate 10
        await run.lease.release()
        await _settled(database, 0)


async def test_one_budget_spans_replicas_and_a_denied_run_calls_no_model(
    database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = UsageAgent()
    async with replica(database, monkeypatch, agent) as one:
        async with replica(database, monkeypatch, agent) as two:
            agent.usage = 950
            await one.invoke(AgentRequest(message="spend"))
            calls = agent.calls
            with pytest.raises(QuotaExceededError) as denied:
                await two.invoke(AgentRequest(message="blocked"))
            assert denied.value.retry_after_seconds > 0
            assert agent.calls == calls


# --- fail closed -------------------------------------------------------------------------


async def test_database_unavailable_fails_admission_closed_without_a_model_call(
    database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = UsageAgent()
    async with replica(database, monkeypatch, agent, postgres_pool_timeout_seconds=1) as service:
        await service.invoke(AgentRequest(message="warm up"))
        calls = agent.calls
        name = make_conninfo(database).split("dbname=")[1].split()[0]
        admin_dsn = _admin_dsn()
        async with await psycopg.AsyncConnection.connect(admin_dsn, autocommit=True) as admin:
            await admin.execute(f'ALTER DATABASE "{name}" ALLOW_CONNECTIONS false')  # nosec B608
            await admin.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s", (name,)
            )
            with structlog.testing.capture_logs() as logs:
                with pytest.raises(PersistenceError) as failure:
                    await service.invoke(AgentRequest(message="no database"))
            assert failure.value.context.http_status == 503
            assert agent.calls == calls
            assert "password" not in str(logs).lower()
            await admin.execute(f'ALTER DATABASE "{name}" ALLOW_CONNECTIONS true')  # nosec B608

        async def serves() -> bool:
            try:
                await service.invoke(AgentRequest(message="recovered"))
            except PersistenceError:
                return False
            return True

        deadline = time.monotonic() + 10
        while not await serves():
            assert time.monotonic() < deadline
            await asyncio.sleep(0.1)


def _admin_dsn() -> str:
    import os  # noqa: PLC0415

    return os.environ["APP_TEST_POSTGRES_DSN"]


async def test_owner_lock_held_past_lock_timeout_fails_closed(
    database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = UsageAgent()
    async with replica(database, monkeypatch, agent, lock_timeout_ms=300) as service:
        lock = "SELECT pg_advisory_xact_lock(hashtextextended('neuron.token_budget:anonymous', 0))"
        async with await psycopg.AsyncConnection.connect(database) as holder:
            await holder.execute(lock)
            started = time.monotonic()
            with pytest.raises(PersistenceError):
                await service.invoke(AgentRequest(message="blocked"))
            assert 0.25 <= time.monotonic() - started < 5
            assert agent.calls == 0
        await service.invoke(AgentRequest(message="free again"))
        assert agent.calls == 1


async def test_a_failed_settlement_delivers_the_answer_and_blocks_the_next_admission(
    database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    monkeypatch.setattr(metrics, "_meter", lambda: provider.get_meter("test"))
    agent = UsageAgent()
    agent.usage = 500  # more than the 100 + estimate reserved, so settling must write
    async with replica(database, monkeypatch, agent, lock_timeout_ms=300) as service:
        blocker = await psycopg.AsyncConnection.connect(database)

        async def lock_the_ledger() -> None:
            await blocker.execute("LOCK TABLE neuron_token_ledger IN ACCESS EXCLUSIVE MODE")

        agent.before_answer = lock_the_ledger  # the ledger goes away after the answer exists
        with structlog.testing.capture_logs() as logs:
            response = await service.invoke(AgentRequest(message="answer anyway"))
        agent.before_answer = None
        assert response.answer == "ok"
        assert any(log["event"] == "token_budget_settle_failed" for log in logs)
        data = reader.get_metrics_data()
        assert data is not None
        [point] = [
            m.data.data_points[0]
            for r in data.resource_metrics
            for s in r.scope_metrics
            for m in s.metrics
            if m.name == semconv.METRIC_BUDGET_SETTLE_FAILURES
        ]
        assert point.value == 1  # type: ignore[union-attr]

        calls = agent.calls
        with pytest.raises(PersistenceError):  # the store still does not answer
            await service.invoke(AgentRequest(message="blocked"))
        assert agent.calls == calls

        await blocker.rollback()
        await blocker.close()
        agent.usage = 20
        await service.invoke(AgentRequest(message="store is back"))
        assert agent.calls == calls + 1
        # The refused settlement was written (500) before the new run was admitted (20).
        await _settled(database, 520)


# --- two Uvicorn processes ---------------------------------------------------------------


async def test_the_budget_holds_across_two_processes(database: str, tmp_path: Path) -> None:
    settings = {"user_token_budget": 1_000, "max_output_tokens": 100}
    one = await AppProcess(database, tmp_path, "one", **settings).wait_ready()
    two = await AppProcess(database, tmp_path, "two", **settings).wait_ready()
    try:
        assert (await one.invoke("use 950", user_id="u")).status_code == 200
        refused = await two.invoke(user_id="u")  # the same principal, on the other process
        assert (refused.status_code, refused.json()) == (429, {"detail": "quota_exceeded"})
        assert 0 < int(refused.headers["Retry-After"]) <= 3600 + 60
        assert (await two.invoke(user_id="someone-else")).status_code == 200
    finally:
        await one.close()
        await two.close()


async def test_the_in_memory_budget_does_not_hold_across_processes(
    database: str, tmp_path: Path
) -> None:
    """The scenario above fails without the Postgres budget: the other process admits."""
    settings = {"limits_backend": "memory", "user_token_budget": 1_000, "max_output_tokens": 100}
    one = await AppProcess(database, tmp_path, "mem-one", **settings).wait_ready()
    two = await AppProcess(database, tmp_path, "mem-two", **settings).wait_ready()
    try:
        assert (await one.invoke("use 950", user_id="u")).status_code == 200
        assert (await two.invoke(user_id="u")).status_code == 200
    finally:
        await one.close()
        await two.close()


async def test_a_ledger_outage_is_a_503_over_http_and_usage_survives_a_restart(
    database: str, tmp_path: Path
) -> None:
    settings = {"user_token_budget": 1_000, "max_output_tokens": 100}
    first = await AppProcess(database, tmp_path, "first", **settings).wait_ready()
    try:
        assert (await first.invoke("use 950", user_id="u")).status_code == 200
    finally:
        await first.close()  # SIGTERM: the process is gone
    second = await AppProcess(database, tmp_path, "second", **settings).wait_ready()
    try:
        assert (await second.invoke(user_id="u")).status_code == 429  # the usage survived
        assert (await second.invoke(user_id="fresh")).status_code == 200
        await rows(database, "ALTER TABLE neuron_token_ledger RENAME TO neuron_token_ledger_off")
        broken = await second.invoke(user_id="fresh")
        assert (broken.status_code, broken.json()) == (
            503,
            {"detail": "internal_server_error"},
        )  # persistence_error, hidden
    finally:
        await second.close()
