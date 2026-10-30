"""Run-lease wiring that needs no database (#146). The Postgres behaviour itself is in
`tests/integration/test_postgres_run_guard.py`."""

from __future__ import annotations

import asyncio
import os
import subprocess  # nosec B404 - runs this repository's own app
import sys
from pathlib import Path
from typing import Any

import psycopg
import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from pydantic import SecretStr

from neuron_agent.config.settings import Settings
from neuron_agent.errors.base import PersistenceError, ThreadBusyError
from neuron_agent.graphs import main_graph
from neuron_agent.observability import metrics, semconv
from neuron_agent.persistence.checkpointer import build_persistence
from neuron_agent.persistence.guards import build_rate_limiter, build_run_guard, build_token_budget
from neuron_agent.persistence.migrations import MIGRATIONS
from neuron_agent.persistence.rate_limiter import PostgresRateLimiter
from neuron_agent.persistence.run_guard import LEASE_GRACE_SECONDS, PostgresRunGuard
from neuron_agent.persistence.token_budget import PostgresTokenBudget
from neuron_agent.schemas.agent import AgentRequest
from neuron_agent.security.run_guard import InMemoryRunGuard, RunClaimDenied
from neuron_agent.services.agent_service import AgentService

pytestmark = pytest.mark.anyio

_DSN = SecretStr("postgresql://neuron:unused@127.0.0.1:1/neuron?connect_timeout=1")
_KEY = SecretStr("k" * 32)


def _postgres_settings() -> Settings:
    return Settings(env="test", limits_backend="postgres", postgres_dsn=_DSN)


def test_postgres_limits_backend_builds_the_postgres_run_guard() -> None:
    settings = _postgres_settings()
    guard = build_run_guard(settings, build_persistence(settings))
    assert isinstance(guard, PostgresRunGuard)


def test_postgres_run_guard_needs_the_pool() -> None:
    with pytest.raises(ValueError, match="connection pool"):
        build_run_guard(_postgres_settings())
    memory = Settings(env="test")
    assert isinstance(build_run_guard(memory, build_persistence(memory)), InMemoryRunGuard)


def test_every_guard_is_postgres_with_the_postgres_backend() -> None:
    settings = Settings(
        env="test", limits_backend="postgres", postgres_dsn=_DSN, identity_hash_key=_KEY
    )
    persistence = build_persistence(settings)
    assert isinstance(build_token_budget(settings, persistence), PostgresTokenBudget)
    assert isinstance(build_run_guard(settings, persistence), PostgresRunGuard)
    assert isinstance(build_rate_limiter(settings, persistence), PostgresRateLimiter)
    for build in (build_token_budget, build_rate_limiter):
        with pytest.raises(ValueError, match="connection pool"):
            build(settings)  # type: ignore[operator]


def test_the_postgres_rate_limiter_needs_the_identity_key_for_its_ip_keys() -> None:
    settings = _postgres_settings()
    with pytest.raises(ValueError, match="APP_IDENTITY_HASH_KEY"):
        build_rate_limiter(settings, build_persistence(settings))
    off = Settings(
        env="test", limits_backend="postgres", postgres_dsn=_DSN, rate_limit_enabled=False
    )
    assert isinstance(build_rate_limiter(off, build_persistence(off)), PostgresRateLimiter)


def _import_app(cwd: Path, **extra: str) -> subprocess.CompletedProcess[str]:
    env = {
        **{k: v for k, v in os.environ.items() if not k.startswith("APP_")},
        "APP_ENV": "test",
        "APP_LIMITS_BACKEND": "postgres",
        "APP_POSTGRES_DSN": _DSN.get_secret_value(),
        **extra,
    }
    return subprocess.run(  # noqa: S603  # nosec B603
        [sys.executable, "-I", "-c", "import neuron_agent.api.main"],
        env=env,
        # Not the repository root: a developer `.env` there must not reach the new process.
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_the_real_app_starts_with_the_postgres_backend(tmp_path: Path) -> None:
    result = _import_app(tmp_path, APP_IDENTITY_HASH_KEY=_KEY.get_secret_value())
    assert result.returncode == 0, result.stderr


def test_the_real_app_without_the_identity_key_stops_without_leaking_the_dsn(
    tmp_path: Path,
) -> None:
    result = _import_app(tmp_path)
    assert result.returncode != 0
    assert "APP_IDENTITY_HASH_KEY is required for shared rate limits" in result.stderr
    assert "unused" not in result.stderr  # the DSN's password never shows


def test_auto_never_selects_postgres() -> None:
    settings = Settings(env="test", postgres_dsn=_DSN)
    assert settings.limits_backend == "memory"


def test_the_lease_table_is_migration_two_and_unique_per_thread() -> None:
    migration = MIGRATIONS[1]
    assert (migration.version, migration.name) == (2, "run_leases")
    assert "thread_id text UNIQUE" in migration.sql
    assert LEASE_GRACE_SECONDS == 15


class _DownPool:
    """A pool whose database is unreachable."""

    def connection(self) -> _DownPool:
        return self

    async def __aenter__(self) -> None:
        raise psycopg.OperationalError("connection refused")

    async def __aexit__(self, *_: object) -> None:
        return None


def _down_guard(*, streams: int = 1) -> PostgresRunGuard:
    return PostgresRunGuard(
        _DownPool(),  # type: ignore[arg-type]
        max_concurrent_streams=streams,
        max_concurrent_runs_per_user=5,
        run_timeout_seconds=120,
    )


async def test_an_unreachable_database_fails_closed_and_frees_the_stream_slot() -> None:
    guard = _down_guard(streams=1)
    for _ in range(3):  # the reserved stream slot is given back each time
        with pytest.raises(PersistenceError):
            await guard.claim(thread_id="t", owner_key="o", streaming=True, guard_thread=True)
    assert guard._open_streams == 0
    for read in (guard.is_thread_active("t"), guard.active_threads_of("o")):
        with pytest.raises(PersistenceError):
            await read


async def test_a_held_thread_blocks_runs_and_uses_no_slot() -> None:
    guard = InMemoryRunGuard(max_concurrent_streams=1, max_concurrent_runs_per_user=1)
    hold = await guard.hold_thread(thread_id="t1", owner_key="a")
    with pytest.raises(RunClaimDenied) as busy:
        await guard.claim(thread_id="t1", owner_key="a", streaming=False, guard_thread=True)
    assert busy.value.reason == "thread_busy"
    with pytest.raises(RunClaimDenied):
        await guard.hold_thread(thread_id="t1", owner_key="a")
    run = await guard.claim(thread_id="t2", owner_key="a", streaming=False, guard_thread=True)
    with pytest.raises(RunClaimDenied):  # a thread with a run on it cannot be held
        await guard.hold_thread(thread_id="t2", owner_key="a")
    await run.release()
    await hold.release()
    assert await guard.active_threads_of("a") == frozenset()


async def test_delete_holds_the_thread_while_it_is_deleted(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.unit.test_run_guards import GatedAgent  # noqa: PLC0415

    agent = GatedAgent()
    agent.gate.set()
    monkeypatch.setattr(main_graph, "build_agent", lambda settings: agent)
    service = AgentService(Settings(env="test"))
    thread_id = (await service.invoke(AgentRequest(message="hi", user_id="u"))).thread_id
    checkpointer: Any = service._persistence.checkpointer
    real = checkpointer.adelete_thread
    entered, proceed = asyncio.Event(), asyncio.Event()

    async def slow(thread: str) -> None:
        entered.set()
        await proceed.wait()
        await real(thread)

    checkpointer.adelete_thread = slow
    deleting = asyncio.create_task(service.delete_thread(thread_id, "u"))
    await entered.wait()
    with pytest.raises(ThreadBusyError):
        await service.prepare(AgentRequest(message="x", thread_id=thread_id, user_id="u"))
    proceed.set()
    await deleting
    assert await service._run_guard.is_thread_active(thread_id) is False


def test_expired_lease_gauge_reports_the_sampled_value(monkeypatch: pytest.MonkeyPatch) -> None:
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    monkeypatch.setattr(metrics, "_meter", lambda: provider.get_meter("test"))
    sampled = [3]
    metrics.observe_expired_leases(lambda: sampled[0])

    def value() -> int:
        data = reader.get_metrics_data()
        assert data is not None
        [point] = [
            m.data.data_points[0]
            for r in data.resource_metrics
            for s in r.scope_metrics
            for m in s.metrics
            if m.name == semconv.METRIC_RUN_LEASES_EXPIRED
        ]
        return int(point.value)

    assert value() == 3
    sampled[0] = 0
    assert value() == 0
    assert semconv.METRIC_RUN_LEASES_EXPIRED == "neuron.run_leases.expired"


async def _two_threads(monkeypatch: pytest.MonkeyPatch) -> tuple[AgentService, list[str], str]:
    from tests.unit.test_run_guards import GatedAgent  # noqa: PLC0415

    agent = GatedAgent()
    agent.gate.set()
    monkeypatch.setattr(main_graph, "build_agent", lambda settings: agent)
    service = AgentService(Settings(env="test"))
    threads = [
        (await service.invoke(AgentRequest(message="hi", user_id="u"))).thread_id for _ in range(2)
    ]
    return service, threads, service._owner_key("u", None) or ""


async def test_erase_counts_only_owned_threads_it_actually_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, threads, owner = await _two_threads(monkeypatch)
    # A run on one owned thread, and a lease on a thread that has no checkpoint (a first run
    # still in flight): only the first is an owned thread that erasure skips.
    busy = await service._run_guard.claim(
        thread_id=threads[0], owner_key=owner, streaming=False, guard_thread=True
    )
    ghost = await service._run_guard.claim(
        thread_id="ghost", owner_key=owner, streaming=False, guard_thread=True
    )
    result = await service.erase_user_data("u")
    assert (result.erased_count, result.skipped_busy_count) == (1, 1)
    await busy.release()
    await ghost.release()


async def test_erase_audits_how_far_it_got_when_it_fails_part_way(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import structlog.testing  # noqa: PLC0415

    service, threads, _ = await _two_threads(monkeypatch)
    checkpointer: Any = service._persistence.checkpointer
    real = checkpointer.adelete_thread
    calls: list[str] = []

    async def flaky(thread_id: str) -> None:
        calls.append(thread_id)
        if len(calls) == 2:
            raise psycopg.OperationalError("connection lost")
        await real(thread_id)

    checkpointer.adelete_thread = flaky
    with structlog.testing.capture_logs() as logs:
        with pytest.raises(PersistenceError):
            await service.erase_user_data("u")
    [event] = [log for log in logs if log["event"] == "user_data_erased"]
    assert (event["outcome"], event["count"], event["reason"]) == ("error", 1, "erasure_failed")
    assert all(thread not in str(event) for thread in threads)  # counts only, no thread IDs
    assert await service._run_guard.active_threads_of(service._owner_key("u", None) or "") == set()
