"""Reserve/settle token budget (#147) without a database.

The Postgres behaviour itself is in `tests/integration/test_postgres_token_budget.py`.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from pydantic import SecretStr

from neuron_agent.config.settings import Settings
from neuron_agent.errors.base import (
    PersistenceError,
    QuotaExceededError,
    RunTimeoutError,
    ThreadBusyError,
)
from neuron_agent.graphs import main_graph
from neuron_agent.observability import metrics, semconv
from neuron_agent.persistence.migrations import MIGRATIONS
from neuron_agent.persistence.token_budget import PostgresTokenBudget, _Handle
from neuron_agent.schemas.agent import AgentAnswer, AgentRequest
from neuron_agent.security.usage_budget import BudgetReservation, InMemoryRollingTokenBudget
from neuron_agent.services.agent_service import AgentService, estimate_prompt_tokens

pytestmark = pytest.mark.anyio


class Clock:
    now = 100.0

    def __call__(self) -> float:
        return self.now


async def _reserve(budget: InMemoryRollingTokenBudget, key: str, tokens: int) -> BudgetReservation:
    decision = await budget.reserve(key, tokens)
    assert decision.allowed and decision.reservation is not None
    return decision.reservation


async def test_reservations_count_at_once_and_settle_to_the_real_usage() -> None:
    budget = InMemoryRollingTokenBudget(token_limit=100, window_seconds=10, clock=Clock())
    first = await _reserve(budget, "a", 60)
    assert (await budget.reserve("a", 60)).allowed is False  # 60 + 60 > 100
    await budget.settle(first, 10)
    await budget.settle(first, 99)  # idempotent: the second settle is ignored
    second = await _reserve(budget, "a", 60)  # 10 + 60 fits
    assert (await budget.reserve("a", 60)).allowed is False
    await budget.settle(second, 0)
    assert (await budget.reserve("a", 90)).allowed is True


async def test_a_reservation_is_capped_at_the_budget_so_a_small_budget_still_admits() -> None:
    budget = InMemoryRollingTokenBudget(token_limit=5, window_seconds=10, clock=Clock())
    held = await _reserve(budget, "a", 2_000)
    assert held.tokens == 5
    assert (await budget.reserve("a", 1)).allowed is False


async def test_retry_after_is_when_enough_usage_leaves_the_window() -> None:
    clock = Clock()
    budget = InMemoryRollingTokenBudget(token_limit=10, window_seconds=10, clock=clock)
    await budget.settle(await _reserve(budget, "a", 4), 4)  # t=100
    clock.now = 103
    await budget.settle(await _reserve(budget, "a", 6), 6)  # t=103
    denied = await budget.reserve("a", 4)
    # Dropping the first 4 tokens (leaving at t=110) is enough; the second would take longer.
    assert (denied.allowed, denied.retry_after_seconds) == (False, 7)


async def test_concurrent_reservations_never_exceed_the_budget() -> None:
    budget = InMemoryRollingTokenBudget(token_limit=10, window_seconds=10, clock=Clock())
    decisions = await asyncio.gather(*(budget.reserve("a", 1) for _ in range(50)))
    assert sum(d.allowed for d in decisions) == 10


async def test_settling_a_reservation_that_aged_out_counts_the_real_usage_now() -> None:
    clock = Clock()
    budget = InMemoryRollingTokenBudget(token_limit=10, window_seconds=10, clock=clock)
    held = await _reserve(budget, "a", 3)
    clock.now += 10
    await budget.settle(held, 9)
    assert (await budget.reserve("a", 5)).allowed is False


# --- service wiring --------------------------------------------------------------------


class UsageAgent:
    def __init__(self, usage: dict[str, int] | None) -> None:
        self.usage = usage
        self.calls = 0

    async def ainvoke(self, *_: Any, context: Any, **__: Any) -> dict[str, Any]:
        self.calls += 1
        if self.usage:
            context.usage.record(self.usage)
        return {
            "messages": [],
            "structured_response": AgentAnswer(answer="ok", used_tools=[], confidence=1.0),
        }


def _service(
    monkeypatch: pytest.MonkeyPatch, usage: dict[str, int] | None, **settings: Any
) -> tuple[AgentService, UsageAgent]:
    agent = UsageAgent(usage)
    monkeypatch.setattr(main_graph, "build_agent", lambda _: agent)
    return AgentService(Settings(env="test", openai_api_key=None, **settings)), agent


def test_the_prompt_estimate_is_high_and_never_zero() -> None:
    assert estimate_prompt_tokens("a") == 1
    assert estimate_prompt_tokens("a" * 30) == 10
    assert estimate_prompt_tokens("é" * 30) == 20  # bytes, not characters


async def test_a_run_without_usage_keeps_its_whole_reservation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = "x" * 30  # an estimate of 10 tokens, so each run reserves 15
    service, agent = _service(monkeypatch, None, user_token_budget=25, max_output_tokens=5)
    await service.invoke(AgentRequest(message=message))  # no usage: settles at 15, not 10
    with pytest.raises(QuotaExceededError):
        await service.prepare(AgentRequest(message=message))  # 15 + 15 > 25
    assert agent.calls == 1


async def test_a_timed_out_run_without_usage_keeps_its_whole_reservation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Hang:
        async def ainvoke(self, *_: Any, **__: Any) -> dict[str, Any]:
            await asyncio.Event().wait()
            return {}

    monkeypatch.setattr(main_graph, "build_agent", lambda _: Hang())
    service = AgentService(
        Settings(
            env="test",
            openai_api_key=None,
            user_token_budget=100,
            max_output_tokens=40,
            run_timeout_seconds=1,
        )
    )
    with pytest.raises(RunTimeoutError):
        await service.invoke(AgentRequest(message="x"))  # reserves 41, settles at 41
    budget = service._token_budget
    assert (await budget.reserve("anonymous", 41)).allowed is True  # 41 + 41 <= 100
    assert (await budget.reserve("anonymous", 41)).allowed is False  # 82 + 41 > 100


async def test_real_usage_replaces_the_reservation(monkeypatch: pytest.MonkeyPatch) -> None:
    service, _ = _service(
        monkeypatch, {"total_tokens": 1}, user_token_budget=100, max_output_tokens=10
    )
    for _ in range(10):  # each run reserves the cap (100) but is settled to 1
        await service.invoke(AgentRequest(message="hi"))


async def test_a_refused_claim_gives_the_reservation_back(monkeypatch: pytest.MonkeyPatch) -> None:
    service, _ = _service(
        monkeypatch,
        {"total_tokens": 1},
        user_token_budget=40,
        max_output_tokens=10,
        checkpointer="memory",
    )
    thread = (await service.invoke(AgentRequest(message="first", user_id="u"))).thread_id
    held = await service.prepare(AgentRequest(message="long", thread_id=thread, user_id="u"))
    for _ in range(5):  # each refused claim reserved 11 and must hand it back (40 would run out)
        with pytest.raises(ThreadBusyError):
            await service.prepare(AgentRequest(message="again", thread_id=thread, user_id="u"))
    await held.lease.release()  # the unstarted run gives its reservation back too
    await service.invoke(AgentRequest(message="after", thread_id=thread, user_id="u"))


async def test_a_denied_run_calls_no_model(monkeypatch: pytest.MonkeyPatch) -> None:
    service, agent = _service(monkeypatch, {"total_tokens": 100}, user_token_budget=100)
    await service.invoke(AgentRequest(message="spend it"))
    with pytest.raises(QuotaExceededError) as denied:
        await service.invoke(AgentRequest(message="blocked"))
    assert denied.value.retry_after_seconds >= 1
    assert agent.calls == 1


# --- Postgres budget, no database ------------------------------------------------------


class _DownPool:
    """A pool whose database is unreachable."""

    def connection(self) -> _DownPool:
        return self

    async def __aenter__(self) -> None:
        raise psycopg.OperationalError("connection refused")

    async def __aexit__(self, *_: object) -> None:
        return None


def _down_budget() -> PostgresTokenBudget:
    return PostgresTokenBudget(_DownPool(), token_limit=100, window_seconds=60)  # type: ignore[arg-type]


async def test_an_unreachable_database_fails_admission_closed() -> None:
    with pytest.raises(PersistenceError):
        await _down_budget().reserve("owner", 10)


async def test_the_service_calls_no_model_when_the_ledger_is_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = UsageAgent({"total_tokens": 1})
    monkeypatch.setattr(main_graph, "build_agent", lambda _: agent)
    service = AgentService(Settings(env="test", openai_api_key=None), token_budget=_down_budget())
    with pytest.raises(PersistenceError) as failure:
        await service.invoke(AgentRequest(message="hi"))
    assert failure.value.context.http_status == 503
    assert agent.calls == 0


async def test_a_failed_settlement_is_counted_never_raised_and_blocks_the_next_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    monkeypatch.setattr(metrics, "_meter", lambda: provider.get_meter("test"))
    budget = _down_budget()
    reservation = BudgetReservation("owner", 10, _Handle(datetime.now(UTC), uuid.uuid4()))

    await budget.settle(reservation, 50)  # the answer is delivered: no exception
    await budget.settle(reservation, 50)  # and a second settle is a no-op

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
    assert budget._unsettled["owner"] == [(reservation, 50)]
    with pytest.raises(PersistenceError):  # still down: that owner's admission fails closed
        await budget.reserve("owner", 1)
    assert budget._unsettled["owner"] == [(reservation, 50)]  # kept for the next attempt


async def test_an_empty_owner_entry_is_dropped_after_expiry() -> None:
    clock = Clock()
    budget = InMemoryRollingTokenBudget(token_limit=10, window_seconds=10, clock=clock)
    held = await _reserve(budget, "a", 3)
    clock.now += 10
    await budget.settle(held, 0)  # aged out and nothing to charge
    assert "a" not in budget._events


class _BrokenPool:
    """A pool failing with something that is not a psycopg error."""

    def connection(self) -> _BrokenPool:
        return self

    async def __aenter__(self) -> None:
        raise OSError("network is gone")

    async def __aexit__(self, *_: object) -> None:
        return None


async def test_a_non_psycopg_failure_is_a_persistence_error_not_a_500() -> None:
    budget = PostgresTokenBudget(_BrokenPool(), token_limit=100, window_seconds=60)  # type: ignore[arg-type]
    with pytest.raises(PersistenceError):
        await budget.reserve("owner", 10)


def test_postgres_needs_a_window_longer_than_a_run() -> None:
    dsn = SecretStr("postgresql://neuron:unused@127.0.0.1:1/neuron")
    with pytest.raises(ValueError, match="at least APP_RUN_TIMEOUT_SECONDS \\+ 15"):
        Settings(
            env="test",
            limits_backend="postgres",
            postgres_dsn=dsn,
            run_timeout_seconds=120,
            user_token_budget_window_seconds=134,
        )
    Settings(
        env="test",
        limits_backend="postgres",
        postgres_dsn=dsn,
        run_timeout_seconds=120,
        user_token_budget_window_seconds=135,
    )
    Settings(env="test", run_timeout_seconds=120, user_token_budget_window_seconds=1)  # memory


def test_the_ledger_is_a_logged_table_added_by_expand_only_migrations() -> None:
    by_name = {m.name: m for m in MIGRATIONS}
    table, index = by_name["token_ledger"], by_name["token_ledger_minute_idx"]
    settlements = by_name["token_settlements"]
    assert "token_settlements_settled_idx" in by_name
    assert "reservation_id uuid PRIMARY KEY" in settlements.sql
    assert (table.version, table.name) == (6, "token_ledger")
    assert (index.version, index.name, index.concurrent) == (7, "token_ledger_minute_idx", True)
    assert "UNLOGGED" not in table.sql.upper()
    assert "PRIMARY KEY (owner_key, minute)" in table.sql


async def test_concurrent_retries_for_one_owner_lose_and_repeat_nothing() -> None:
    budget = _down_budget()
    first = BudgetReservation("o", 10, _Handle(datetime.now(UTC), uuid.uuid4()))
    second = BudgetReservation("o", 10, _Handle(datetime.now(UTC), uuid.uuid4()))
    budget._unsettled["o"] = [(first, 50), (second, 60)]
    written: list[BudgetReservation] = []
    attempts = 0

    async def write(reservation: BudgetReservation, actual: int) -> None:
        nonlocal attempts
        attempts += 1
        await asyncio.sleep(0)
        if attempts == 1:
            raise PersistenceError("down")  # the first write fails; the retry must go on
        written.append(reservation)

    budget._write = write  # type: ignore[method-assign]
    results = await asyncio.gather(
        budget._retry_unsettled("o"), budget._retry_unsettled("o"), return_exceptions=True
    )
    assert sum(isinstance(r, PersistenceError) for r in results) == 1
    assert written == [first, second]  # each entry written once, in order, none dropped
    assert "o" not in budget._unsettled
    assert budget._retry_locks == {}
