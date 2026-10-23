"""Shared run leases in Postgres (#146, ADR 0008 decision 8), against a real database.

Guard-level tests use `PostgresRunGuard` directly; service-level tests run two `AgentService`
replicas on one database; the HTTP tests run two Uvicorn processes (`pg_harness.py`).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any

import anyio
import psycopg
import pytest
import structlog.testing
from pg_harness import AppProcess
from psycopg.conninfo import make_conninfo
from pydantic import SecretStr

from neuron_agent.api import main as api_main
from neuron_agent.config.settings import Settings
from neuron_agent.errors.base import (
    AppError,
    PersistenceError,
    RunTimeoutError,
    ThreadBusyError,
    ThreadNotFoundError,
)
from neuron_agent.graphs import main_graph
from neuron_agent.observability import metrics
from neuron_agent.persistence import guards, run_guard
from neuron_agent.persistence.checkpointer import build_persistence
from neuron_agent.persistence.retention import prune_threads
from neuron_agent.persistence.run_guard import PostgresRunGuard
from neuron_agent.schemas.agent import AgentAnswer, AgentRequest
from neuron_agent.security.run_guard import RunClaimDenied
from neuron_agent.services.agent_service import AgentService

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.anyio]

_ADMIN_DSN = os.environ.get("APP_TEST_POSTGRES_DSN", "")


# --- helpers ---------------------------------------------------------------------------


async def rows(dsn: str, query: str, *params: object) -> list[tuple[Any, ...]]:
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as conn:
        cursor = await conn.execute(query, params)  # type: ignore[call-overload]
        return await cursor.fetchall() if cursor.description else []


async def scalar(dsn: str, query: str, *params: object) -> Any:
    return (await rows(dsn, query, *params))[0][0]


async def lease_count(dsn: str) -> int:
    return int(await scalar(dsn, "SELECT count(*) FROM neuron_run_leases"))


async def eventually(check: Callable[[], Awaitable[bool]], *, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while not await check():
        assert time.monotonic() < deadline, "condition not reached in time"
        await asyncio.sleep(0.05)


async def wait_for_lease(dsn: str, *, thread_id: str | None = None) -> float:
    """Wait until a run lease exists (for `thread_id`); returns seconds until it expires."""
    where, params = ("thread_id = %s", (thread_id,)) if thread_id else ("true", ())
    query = (
        f"SELECT extract(epoch FROM max(expires_at) - now()) FROM neuron_run_leases WHERE {where}"  # noqa: S608  # nosec B608
    )
    remaining: list[float] = []

    async def present() -> bool:
        value = await scalar(dsn, query, *params)
        if value is not None:
            remaining.append(float(value))
        return bool(remaining)

    await eventually(present)
    return remaining[0]


class ScriptedAgent:
    """Stands in for the model: counts calls, can block on `gate`, or fail."""

    def __init__(self, *, fail: bool = False) -> None:
        self.calls = 0
        self.started = asyncio.Event()
        self.gate = asyncio.Event()
        self.gate.set()
        self.fail = fail

    async def ainvoke(self, inputs: dict[str, Any], **_: Any) -> dict[str, Any]:
        self.calls += 1
        self.started.set()
        await self.gate.wait()
        if self.fail:
            raise RuntimeError("model unavailable")
        answer = AgentAnswer(answer="ok", used_tools=[], confidence=1.0)
        return {"messages": [], "structured_response": answer}

    def hold(self) -> None:
        self.gate.clear()
        self.started.clear()


@contextmanager
def _in_process(monkeypatch: pytest.MonkeyPatch, agent: ScriptedAgent) -> Any:
    # The rate limiter and token budget have no Postgres version yet (#147, #148).
    monkeypatch.setattr(guards, "_require_memory", lambda settings: None)
    monkeypatch.setattr(main_graph, "build_agent", lambda settings: agent)
    yield


def _settings(dsn: str, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "env": "test",
        "checkpointer": "postgres",
        "limits_backend": "postgres",
        "postgres_dsn": SecretStr(dsn),
        "max_concurrent_runs_per_user": 100,
    }
    return Settings(**{**values, **overrides})


@asynccontextmanager
async def replica(
    dsn: str,
    monkeypatch: pytest.MonkeyPatch,
    agent: ScriptedAgent,
    *,
    lock_timeout_ms: int | None = None,
    **settings: Any,
) -> AsyncIterator[AgentService]:
    """One app replica (a service with its own pool) on `dsn`."""
    with _in_process(monkeypatch, agent):
        resolved = _settings(dsn, **settings)
        persistence = build_persistence(resolved)
        guard = None
        if lock_timeout_ms is not None:
            assert persistence.pool is not None
            guard = PostgresRunGuard(
                persistence.pool,
                max_concurrent_streams=resolved.max_concurrent_streams,
                max_concurrent_runs_per_user=resolved.max_concurrent_runs_per_user,
                run_timeout_seconds=resolved.run_timeout_seconds,
                lock_timeout_ms=lock_timeout_ms,
            )
        service = AgentService(resolved, persistence=persistence, run_guard=guard)
        await service.startup()
    try:
        yield service
    finally:
        await service.shutdown()


@asynccontextmanager
async def guard_on(dsn: str, **overrides: Any) -> AsyncIterator[PostgresRunGuard]:
    """A bare guard on its own pool; two of these are two replicas."""
    lock_timeout_ms = overrides.pop("lock_timeout_ms", run_guard.DEFAULT_LOCK_TIMEOUT_MS)
    persistence = build_persistence(_settings(dsn, checkpointer="none", **overrides))
    await persistence.open()
    assert persistence.pool is not None
    try:
        yield PostgresRunGuard(
            persistence.pool,
            max_concurrent_streams=100,
            max_concurrent_runs_per_user=overrides.get("max_concurrent_runs_per_user", 100),
            run_timeout_seconds=overrides.get("run_timeout_seconds", 120),
            lock_timeout_ms=lock_timeout_ms,
        )
    finally:
        await persistence.close()


async def _claim(guard: PostgresRunGuard, thread: str, owner: str = "owner") -> Any:
    return await guard.claim(thread_id=thread, owner_key=owner, streaming=False, guard_thread=True)


def _reasons(results: list[Any]) -> list[str]:
    return sorted(r.reason if isinstance(r, RunClaimDenied) else type(r).__name__ for r in results)


# --- guard: claims, caps, barrier ------------------------------------------------------


async def test_claim_release_and_the_thread_and_owner_rules(database: str) -> None:
    async with guard_on(database, max_concurrent_runs_per_user=2) as guard:
        first = await _claim(guard, "t1")
        assert await guard.is_thread_active("t1") is True
        assert await guard.active_threads_of("owner") == {"t1"}
        with pytest.raises(RunClaimDenied) as busy:
            await _claim(guard, "t1")
        assert busy.value.reason == "thread_busy"
        await _claim(guard, "t2")
        with pytest.raises(RunClaimDenied) as capped:
            await _claim(guard, "t3")
        assert capped.value.reason == "concurrent_runs"
        assert await lease_count(database) == 2

        await first.release()
        await first.release()  # idempotent
        assert await guard.is_thread_active("t1") is False
        assert await lease_count(database) == 1
        await _claim(guard, "t3")  # the freed slot

        # Without persistence, `thread_id` is only a correlation ID: no thread guard.
        a = await guard.claim(thread_id="x", owner_key="o2", streaming=False, guard_thread=False)
        b = await guard.claim(thread_id="x", owner_key="o3", streaming=False, guard_thread=False)
        assert (
            await scalar(database, "SELECT count(*) FROM neuron_run_leases WHERE owner_key='o2'")
            == 1
        )
        await a.release()
        await b.release()


async def test_holding_a_thread_blocks_runs_but_uses_no_slot(database: str) -> None:
    async with guard_on(database, max_concurrent_runs_per_user=1) as guard:
        hold = await guard.hold_thread(thread_id="t1", owner_key="owner")
        with pytest.raises(RunClaimDenied) as denied:
            await _claim(guard, "t1")
        assert denied.value.reason == "thread_busy"
        with pytest.raises(RunClaimDenied):
            await guard.hold_thread(thread_id="t1", owner_key="owner")
        run = await _claim(guard, "t2")  # the cap of 1 is still free for a run
        await run.release()
        await hold.release()
        await (await _claim(guard, "t1")).release()


async def test_stream_cap_is_per_process_and_counts_only_streams(database: str) -> None:
    async with guard_on(database) as guard:
        small = PostgresRunGuard(
            guard._pool,
            max_concurrent_streams=1,
            max_concurrent_runs_per_user=100,
            run_timeout_seconds=120,
        )
        stream = await small.claim(thread_id="a", owner_key="o", streaming=True, guard_thread=True)
        with pytest.raises(RunClaimDenied) as denied:
            await small.claim(thread_id="b", owner_key="o", streaming=True, guard_thread=True)
        assert denied.value.reason == "concurrent_streams"
        assert await lease_count(database) == 1  # the refused claim left nothing behind
        await (await _claim(small, "c")).release()  # a plain run is not a stream
        await stream.release()
        await (
            await small.claim(thread_id="d", owner_key="o", streaming=True, guard_thread=True)
        ).release()


async def test_barrier_exactly_k_claims_succeed_per_owner_across_replicas(database: str) -> None:
    k = 3
    async with guard_on(database, max_concurrent_runs_per_user=k) as one:
        async with guard_on(database, max_concurrent_runs_per_user=k) as two:
            attempts = [
                _claim([one, two][i % 2], f"thread-{i}", owner="same-owner") for i in range(40)
            ]
            results = await asyncio.gather(*attempts, return_exceptions=True)
            assert _reasons(results) == sorted(["concurrent_runs"] * 37 + ["RunLease"] * 3)
            assert await lease_count(database) == k
            # Another owner has its own budget, unaffected by the first one's.
            await (await _claim(one, "other-thread", owner="other-owner")).release()


async def test_barrier_exactly_one_claim_succeeds_per_thread_never_a_500(database: str) -> None:
    async with guard_on(database) as one:
        async with guard_on(database) as two:
            same_owner = [_claim([one, two][i % 2], "shared", owner="a") for i in range(40)]
            results = await asyncio.gather(*same_owner, return_exceptions=True)
            assert _reasons(results) == ["RunLease"] + ["thread_busy"] * 39
            await asyncio.gather(*(r.release() for r in results if not isinstance(r, Exception)))

            # Different owners are not serialised by the advisory lock, so the unique
            # constraint itself decides; its violation is `thread_busy`, not an error.
            owners = [_claim([one, two][i % 2], "shared-2", owner=f"o{i}") for i in range(40)]
            results = await asyncio.gather(*owners, return_exceptions=True)
            assert _reasons(results) == ["RunLease"] + ["thread_busy"] * 39


# --- guard: expiry and the database clock ---------------------------------------------


async def test_expiry_is_run_timeout_plus_15_seconds_by_the_database_clock(
    database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with guard_on(database, run_timeout_seconds=1) as guard:
        remaining = (
            "SELECT extract(epoch FROM expires_at - now())"
            " FROM neuron_run_leases WHERE thread_id=%s"
        )
        real_time = time.time
        for name, skew in (("ahead", 10 * 365 * 86400), ("behind", -10 * 365 * 86400)):
            with monkeypatch.context() as patch:
                patch.setattr(time, "time", lambda skew=skew: real_time() + skew)
                lease = await _claim(guard, f"skewed-{name}")
                # 1 s run timeout + 15 s, whatever the application clock says.
                assert 15.0 < await scalar(database, remaining, f"skewed-{name}") <= 16.0
                # A clock ten years ahead does not make the lease look expired.
                assert await guard.is_thread_active(f"skewed-{name}") is True
                with pytest.raises(RunClaimDenied):
                    await _claim(guard, f"skewed-{name}")
            await lease.release()

        # Let it expire for real (grace shortened so the test takes seconds): the thread is
        # usable again once the database clock passes `expires_at`, and not before.
        monkeypatch.setattr(run_guard, "LEASE_GRACE_SECONDS", 1)
        async with guard_on(database, run_timeout_seconds=1) as quick:
            await _claim(quick, "left-behind")  # never released: a "killed" process
            with monkeypatch.context() as patch:
                patch.setattr(time, "time", lambda: real_time() - 10 * 365 * 86400)
                with pytest.raises(RunClaimDenied):
                    await _claim(quick, "left-behind")
                await asyncio.sleep(2.2)
                replaced = await _claim(quick, "left-behind")  # expired: deleted and re-claimed
            await replaced.release()
            assert await lease_count(database) == 0


async def test_killed_process_blocks_for_run_timeout_plus_15_seconds(
    database: str, tmp_path: Path
) -> None:
    survivor = await AppProcess(database, tmp_path, "survivor").wait_ready()
    victim = await AppProcess(database, tmp_path, "victim", run_timeout_seconds=3).wait_ready()
    try:
        thread = (await victim.invoke(user_id="u")).json()["thread_id"]
        running = asyncio.create_task(victim.invoke("hang", thread_id=thread, user_id="u"))
        remaining = await wait_for_lease(database, thread_id=thread)
        detected = time.monotonic()
        victim.kill()  # no release, no shutdown hook
        assert 17.0 < remaining <= 18.0  # 3 s run timeout + 15 s, by the database clock
        with pytest.raises(Exception):  # noqa: B017 - the connection died with the process
            await running

        refused = await survivor.invoke(thread_id=thread, user_id="u")
        assert (refused.status_code, refused.json()) == (409, {"detail": "thread_busy"})
        while (response := await survivor.invoke(thread_id=thread, user_id="u")).status_code == 409:
            assert time.monotonic() - detected < remaining + 8, "the lease never expired"
            await asyncio.sleep(1)
        assert response.status_code == 200
        assert time.monotonic() - detected >= remaining - 1.5  # not before it expired
    finally:
        await victim.close()
        await survivor.close()


# --- guard: release failures, fail-closed, retention, gauge ----------------------------


async def test_release_failure_never_raises_and_expiry_covers_it(database: str) -> None:
    async with guard_on(database, lock_timeout_ms=300) as guard:
        lease = await _claim(guard, "t1")
        async with await psycopg.AsyncConnection.connect(database) as blocker:
            await blocker.execute("LOCK TABLE neuron_run_leases IN ACCESS EXCLUSIVE MODE")
            with structlog.testing.capture_logs() as logs:
                await lease.release()  # blocked past lock_timeout: swallowed, logged
        assert any(log["event"] == "run_lease_release_failed" for log in logs)
        assert await lease_count(database) == 1  # still there; only expiry removes it
        await rows(
            database, "UPDATE neuron_run_leases SET expires_at = now() - interval '1 second'"
        )
        await (await _claim(guard, "t1")).release()  # an expired lease no longer blocks


async def test_database_unavailable_fails_closed_without_a_model_call(
    database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = ScriptedAgent()
    async with replica(database, monkeypatch, agent, postgres_pool_timeout_seconds=1) as service:
        assert (await service.invoke(AgentRequest(message="warm up"))).answer == "ok"
        calls = agent.calls
        name = make_conninfo(database).split("dbname=")[1].split()[0]
        async with await psycopg.AsyncConnection.connect(_ADMIN_DSN, autocommit=True) as admin:
            await admin.execute(f'ALTER DATABASE "{name}" ALLOW_CONNECTIONS false')  # nosec B608
            await admin.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s", (name,)
            )
            with structlog.testing.capture_logs():
                with pytest.raises(PersistenceError) as failure:
                    await service.invoke(AgentRequest(message="no database"))
            assert failure.value.context.code == "persistence_error"
            assert failure.value.context.http_status == 503
            assert agent.calls == calls
            await admin.execute(f'ALTER DATABASE "{name}" ALLOW_CONNECTIONS true')  # nosec B608
        await eventually(lambda: _serves(service))


async def _serves(service: AgentService) -> bool:
    try:
        await service.invoke(AgentRequest(message="recovered"))
    except PersistenceError:
        return False
    return True


async def test_owner_lock_held_past_lock_timeout_fails_closed(
    database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = ScriptedAgent()
    async with replica(database, monkeypatch, agent, lock_timeout_ms=300) as service:
        owner_lock = (
            "SELECT pg_advisory_xact_lock(hashtextextended('neuron.run_lease:anonymous', 0))"
        )
        async with await psycopg.AsyncConnection.connect(database) as holder:
            await holder.execute(owner_lock)  # a transaction that keeps the owner's lock
            started = time.monotonic()
            with pytest.raises(PersistenceError):
                await service.invoke(AgentRequest(message="blocked"))
            assert 0.25 <= time.monotonic() - started < 5
            assert agent.calls == 0
        assert (await service.invoke(AgentRequest(message="free again"))).answer == "ok"
        assert agent.calls == 1


async def test_pool_exhausted_fails_closed_without_a_model_call(
    database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = ScriptedAgent()
    async with replica(
        database, monkeypatch, agent, postgres_pool_max_size=4, postgres_pool_timeout_seconds=1
    ) as service:
        pool = service._persistence.pool
        assert pool is not None
        async with contextlib.AsyncExitStack() as taken:
            for _ in range(4):  # every connection of the pool is in use
                await taken.enter_async_context(pool.connection())
            started = time.monotonic()
            with pytest.raises(PersistenceError):
                await service.invoke(AgentRequest(message="no connection"))
            assert 0.9 <= time.monotonic() - started < 5
        assert agent.calls == 0
        assert (await service.invoke(AgentRequest(message="free again"))).answer == "ok"


async def test_unreachable_database_is_a_503_over_http(database: str, tmp_path: Path) -> None:
    app = await AppProcess(database, tmp_path, "app", postgres_pool_timeout_seconds=1).wait_ready()
    try:
        assert (await app.invoke()).status_code == 200
        name = make_conninfo(database).split("dbname=")[1].split()[0]
        async with await psycopg.AsyncConnection.connect(_ADMIN_DSN, autocommit=True) as admin:
            await admin.execute(f'ALTER DATABASE "{name}" ALLOW_CONNECTIONS false')  # nosec B608
            await admin.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s", (name,)
            )
            for path_body in ({}, {"thread_id": "6f9619ff-8b86-d011-b42d-00c04fc964ff"}):
                response = await app.invoke(**path_body)
                assert response.status_code == 503
            await admin.execute(f'ALTER DATABASE "{name}" ALLOW_CONNECTIONS true')  # nosec B608
    finally:
        await app.close()


async def test_retention_deletes_expired_leases_and_the_gauge_counts_them(
    database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[Callable[[], int]] = []
    monkeypatch.setattr(metrics, "observe_expired_leases", seen.append)
    monkeypatch.setattr(run_guard, "EXPIRED_SAMPLE_INTERVAL_SECONDS", 0.05)
    async with guard_on(database) as guard:
        live = await _claim(guard, "live")
        await _claim(guard, "dead-1")
        await _claim(guard, "dead-2")
        await rows(
            database,
            "UPDATE neuron_run_leases SET expires_at = now() - interval '1 minute'"
            " WHERE starts_with(thread_id, 'dead-')",
        )
        assert await guard.count_expired() == 2
        guard.start()
        try:
            [read] = seen

            async def sampled() -> bool:
                return read() == 2

            await eventually(sampled)
        finally:
            await guard.close()

        persistence = build_persistence(_settings(database))
        await persistence.open()
        try:
            await prune_threads(persistence, older_than=timedelta(days=365), delete_leases=True)
        finally:
            await persistence.close()
        assert await guard.count_expired() == 0
        assert await guard.active_threads_of("owner") == {"live"}
        await live.release()


# --- services on two replicas: delete and erase hold a lease ---------------------------


def _blocking_delete(service: AgentService) -> tuple[asyncio.Event, asyncio.Event, list[str]]:
    """Make this replica's thread deletion wait on `proceed` after it has started."""
    checkpointer = service._persistence.checkpointer
    assert checkpointer is not None
    real = checkpointer.adelete_thread
    entered, proceed, deleting = asyncio.Event(), asyncio.Event(), []

    async def slow(thread_id: str) -> None:
        deleting.append(thread_id)
        entered.set()
        await proceed.wait()
        await real(thread_id)

    checkpointer.adelete_thread = slow  # type: ignore[method-assign]
    return entered, proceed, deleting


async def _thread(service: AgentService, user: str) -> str:
    return (await service.invoke(AgentRequest(message="first", user_id=user))).thread_id


async def test_no_run_starts_on_a_thread_while_its_delete_is_in_progress(
    database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = ScriptedAgent()
    async with replica(database, monkeypatch, agent) as one:
        async with replica(database, monkeypatch, agent) as two:
            thread = await _thread(one, "alice")
            entered, proceed, _ = _blocking_delete(one)
            deleting = asyncio.create_task(one.delete_thread(thread, "alice"))
            await entered.wait()
            held = await scalar(
                database, "SELECT kind FROM neuron_run_leases WHERE thread_id=%s", thread
            )
            assert held == "delete"

            request = AgentRequest(message="too early", thread_id=thread, user_id="alice")
            with pytest.raises(ThreadBusyError):
                await two.invoke(request)  # a different replica
            with pytest.raises(ThreadBusyError):
                await two.prepare(request, streaming=True)
            with pytest.raises(ThreadBusyError):
                await two.delete_thread(thread, "alice")
            calls = agent.calls

            proceed.set()
            await deleting
            assert await lease_count(database) == 0
            with pytest.raises(ThreadNotFoundError):
                await two.invoke(request)  # the thread is gone, and nothing re-created it
            assert agent.calls == calls


async def test_delete_refuses_a_live_run_on_another_replica(
    database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = ScriptedAgent()
    async with replica(database, monkeypatch, agent) as one:
        async with replica(database, monkeypatch, agent) as two:
            thread = await _thread(one, "alice")
            agent.hold()
            running = asyncio.create_task(
                one.invoke(AgentRequest(message="long", thread_id=thread, user_id="alice"))
            )
            await agent.started.wait()
            with pytest.raises(ThreadBusyError):
                await two.delete_thread(thread, "alice")
            agent.gate.set()
            await running
            history = await two.get_history(thread, "alice", limit=50, offset=0)
            assert [m.content for m in history.messages] == ["first", "ok", "long", "ok"]
            await two.delete_thread(thread, "alice")  # free now


async def test_bulk_erase_holds_each_thread_and_skips_live_runs(
    database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = ScriptedAgent()
    async with replica(database, monkeypatch, agent) as one:
        async with replica(database, monkeypatch, agent) as two:
            threads = [await _thread(one, "alice") for _ in range(3)]
            entered, proceed, deleting = _blocking_delete(one)
            erasing = asyncio.create_task(one.erase_user_data("alice"))
            await entered.wait()
            in_progress = deleting[0]
            with pytest.raises(ThreadBusyError):
                await two.invoke(AgentRequest(message="x", thread_id=in_progress, user_id="alice"))
            proceed.set()
            result = await erasing
            assert (result.erased_count, result.skipped_busy_count) == (3, 0)
            assert await lease_count(database) == 0

            # A run live on the other replica is skipped, and its thread survives.
            threads = [await _thread(one, "bob") for _ in range(2)]
            agent.hold()
            running = asyncio.create_task(
                two.invoke(AgentRequest(message="long", thread_id=threads[0], user_id="bob"))
            )
            await agent.started.wait()
            result = await one.erase_user_data("bob")
            assert (result.erased_count, result.skipped_busy_count) == (1, 1)
            agent.gate.set()
            await running
            assert (await two.get_history(threads[0], "bob", limit=50, offset=0)).messages[
                -1
            ].content == "ok"


# --- leases never leak: the existing lease scenarios, on both implementations ----------


@pytest.fixture(params=["memory", "postgres"])
async def backend(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, database: str
) -> Any:
    """Yields `(make_service, idle)` for one guard implementation."""
    agent = ScriptedAgent()
    if request.param == "memory":

        async def make(**settings: Any) -> AgentService:
            monkeypatch.setattr(main_graph, "build_agent", lambda s: agent)
            return AgentService(Settings(env="test", **settings))

        async def idle(service: AgentService) -> bool:
            g: Any = service._run_guard
            return not g._active_threads and g._open_streams == 0 and not g._active_runs_by_owner

        yield make, idle, agent
        return

    dsn = database
    stack: list[Any] = []

    async def make_pg(**settings: Any) -> AgentService:
        context = replica(dsn, monkeypatch, agent, **settings)
        stack.append(context)
        return await context.__aenter__()

    async def idle_pg(_: AgentService) -> bool:
        return await lease_count(dsn) == 0

    yield make_pg, idle_pg, agent
    for context in reversed(stack):
        await context.__aexit__(None, None, None)


async def _settled(idle: Callable[[AgentService], Awaitable[bool]], service: AgentService) -> None:
    async def check() -> bool:
        return await idle(service)

    await eventually(check, timeout=5)


async def test_leases_are_released_on_success_failure_timeout_and_cancellation(
    backend: Any,
) -> None:
    make, idle, agent = backend
    service = await make(run_timeout_seconds=1)

    await service.invoke(AgentRequest(message="success"))
    await _settled(idle, service)

    agent.fail = True
    with pytest.raises(AppError):
        await service.invoke(AgentRequest(message="failure"))
    await _settled(idle, service)
    agent.fail = False

    agent.hold()
    with pytest.raises(RunTimeoutError):
        await service.invoke(AgentRequest(message="timeout"))
    await _settled(idle, service)

    agent.hold()
    cancelled = asyncio.create_task(service.invoke(AgentRequest(message="cancelled")))
    await agent.started.wait()
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    await _settled(idle, service)


async def test_leases_are_released_when_a_stream_is_closed_or_its_client_goes_away(
    backend: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    make, idle, agent = backend
    service = await make()
    agent.hold()
    run = await service.prepare(AgentRequest(message="stream"), streaming=True)
    stream = service.stream(run)
    assert (await anext(stream)).event == "run_started"
    pending = asyncio.ensure_future(anext(stream))
    await agent.started.wait()
    pending.cancel()  # the client disconnected while waiting for the next event
    with pytest.raises(asyncio.CancelledError):
        await pending
    await stream.aclose()
    await _settled(idle, service)

    # anyio's cancel scope, the way sse-starlette cancels a stream on disconnect.
    agent.hold()
    run = await service.prepare(AgentRequest(message="stream"), streaming=True)
    stream = service.stream(run)

    async def consume() -> None:
        async for _ in stream:
            pass

    async with anyio.create_task_group() as group:
        group.start_soon(consume)
        await agent.started.wait()
        group.cancel_scope.cancel()
    await _settled(idle, service)

    # The response fails before streaming starts (send timeout and early disconnects take
    # the same path): the response class releases the lease in its `finally`.
    monkeypatch.setattr(api_main, "service", service)
    agent.gate.set()
    response = await api_main.stream_agent(AgentRequest(message="hi"))

    async def receive() -> dict[str, Any]:
        await anyio.sleep_forever()
        return {}  # pragma: no cover

    async def send(message: dict[str, Any]) -> None:
        raise OSError("client went away")

    scope = {"type": "http", "method": "POST", "path": "/v1/agent/stream", "headers": []}
    with pytest.raises(BaseException):  # noqa: B017 - sse-starlette may wrap it in a group
        await response(scope, receive, send)
    await _settled(idle, service)


# --- two Uvicorn processes ---------------------------------------------------------------


async def test_per_user_cap_and_thread_busy_hold_across_processes(
    database: str, tmp_path: Path
) -> None:
    one = await AppProcess(database, tmp_path, "one", max_concurrent_runs_per_user=1).wait_ready()
    two = await AppProcess(database, tmp_path, "two", max_concurrent_runs_per_user=1).wait_ready()
    try:
        thread = (await one.invoke(user_id="u")).json()["thread_id"]
        running = asyncio.create_task(one.invoke("hold 4", thread_id=thread, user_id="u"))
        await wait_for_lease(database, thread_id=thread)

        capped = await two.invoke(user_id="u")  # the same principal, on the other process
        assert (capped.status_code, capped.json()) == (429, {"detail": "too_many_concurrent_runs"})
        assert (await two.invoke(user_id="someone-else")).status_code == 200  # another principal
        assert (await running).status_code == 200
        assert (await two.invoke(thread_id=thread, user_id="u")).status_code == 200  # released
    finally:
        await one.close()
        await two.close()

    one = await AppProcess(database, tmp_path, "one-b", max_concurrent_runs_per_user=2).wait_ready()
    two = await AppProcess(database, tmp_path, "two-b", max_concurrent_runs_per_user=2).wait_ready()
    try:
        thread = (await one.invoke(user_id="v")).json()["thread_id"]
        running = asyncio.create_task(one.invoke("hold 4", thread_id=thread, user_id="v"))
        await wait_for_lease(database, thread_id=thread)
        busy = await two.invoke(thread_id=thread, user_id="v")  # the same thread, other process
        assert (busy.status_code, busy.json()) == (409, {"detail": "thread_busy"})
        await running
    finally:
        await one.close()
        await two.close()


async def test_the_in_memory_guard_does_not_hold_across_processes(
    database: str, tmp_path: Path
) -> None:
    """The scenarios above fail without the Postgres guard: both runs are admitted."""
    settings = {"limits_backend": "memory", "max_concurrent_runs_per_user": 1}
    one = await AppProcess(database, tmp_path, "mem-one", **settings).wait_ready()
    two = await AppProcess(database, tmp_path, "mem-two", **settings).wait_ready()
    try:
        thread = (await one.invoke(user_id="u")).json()["thread_id"]
        running = asyncio.create_task(one.invoke("hold 3", thread_id=thread, user_id="u"))
        await asyncio.sleep(1)
        assert (await two.invoke(user_id="u")).status_code == 200  # over the per-user cap
        assert (await two.invoke(thread_id=thread, user_id="u")).status_code == 200  # busy thread
        await running
    finally:
        await one.close()
        await two.close()


async def test_barrier_across_two_processes_admits_exactly_k_and_exactly_one(
    database: str, tmp_path: Path
) -> None:
    k = 3
    one = await AppProcess(database, tmp_path, "b1", max_concurrent_runs_per_user=k).wait_ready()
    two = await AppProcess(database, tmp_path, "b2", max_concurrent_runs_per_user=k).wait_ready()
    try:
        servers = [one, two]
        capped = await asyncio.gather(
            *(servers[i % 2].invoke("hold 4", user_id="cap") for i in range(24))
        )
        statuses = sorted(r.status_code for r in capped)
        assert statuses == [200] * k + [429] * (24 - k)

        thread = (await one.invoke(user_id="thread")).json()["thread_id"]
        raced = await asyncio.gather(
            *(
                servers[i % 2].invoke("hold 3", thread_id=thread, user_id="thread")
                for i in range(24)
            )
        )
        outcomes = sorted(
            (r.status_code, r.json().get("detail")) for r in raced if r.status_code != 200
        )
        assert outcomes == [(409, "thread_busy")] * 23
        assert sum(r.status_code == 200 for r in raced) == 1
    finally:
        await one.close()
        await two.close()


async def test_a_run_at_the_timeout_is_cancelled_before_its_lease_could_expire(
    database: str, tmp_path: Path
) -> None:
    app = await AppProcess(database, tmp_path, "boundary", run_timeout_seconds=2).wait_ready()
    try:
        thread = (await app.invoke(user_id="u")).json()["thread_id"]
        history = f"/v1/threads/{thread}/messages"
        before = (await app.get(history, user_id="u")).json()
        assert len(before["messages"]) == 2

        running = asyncio.create_task(app.invoke("hold 30", thread_id=thread, user_id="u"))
        remaining = await wait_for_lease(database, thread_id=thread)
        expires_at = await scalar(database, "SELECT expires_at FROM neuron_run_leases")
        response = await running
        assert (response.status_code, response.json()) == (504, {"detail": "run_timeout"})

        # The run ended at its 2 s timeout; its lease was good for 17 s, so the 15 s of
        # grace were still ahead, and the cancelled run committed nothing.
        assert 16.0 < remaining <= 17.0
        assert await scalar(database, "SELECT now() < %s - interval '10 seconds'", expires_at)
        assert (await app.get(history, user_id="u")).json() == before
        assert await lease_count(database) == 0
        assert (await app.invoke(thread_id=thread, user_id="u")).status_code == 200
    finally:
        await app.close()


# --- review follow-ups ------------------------------------------------------------------


async def test_a_wait_for_the_owner_lock_does_not_shorten_the_lease(database: str) -> None:
    async with guard_on(database, run_timeout_seconds=1) as guard:
        lock = "SELECT pg_advisory_xact_lock(hashtextextended('neuron.run_lease:owner', 0))"
        async with await psycopg.AsyncConnection.connect(database) as holder:
            await holder.execute(lock)
            claiming = asyncio.create_task(_claim(guard, "waited"))
            await asyncio.sleep(1.5)  # the claim's transaction started 1.5 s ago
            await holder.rollback()
            lease = await claiming
        remaining = await scalar(
            database,
            "SELECT extract(epoch FROM expires_at - clock_timestamp())"
            " FROM neuron_run_leases WHERE thread_id = 'waited'",
        )
        # 1 s run timeout + 15 s, counted from the insert and not from the transaction start.
        assert 15.7 < remaining <= 16.0
        await lease.release()


async def test_a_claim_cancelled_after_its_commit_leaves_no_lease(
    database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with guard_on(database) as guard:
        real = guard._insert_run

        async def committed_then_stuck(*args: Any) -> None:
            await real(*args)  # the row is committed ...
            await asyncio.sleep(30)  # ... and the caller is cancelled before it learns the id

        monkeypatch.setattr(guard, "_insert_run", committed_then_stuck)
        claiming = asyncio.create_task(_claim(guard, "cancelled"))

        async def committed() -> bool:
            return await lease_count(database) == 1

        await eventually(committed)
        claiming.cancel()
        with pytest.raises(asyncio.CancelledError):
            await claiming

        async def gone() -> bool:
            return await lease_count(database) == 0

        await eventually(gone)
        assert guard._open_streams == 0 and not guard._sent


async def test_thread_pruning_survives_a_missing_lease_table(database: str) -> None:
    agent = ScriptedAgent()
    monkeypatch = pytest.MonkeyPatch()
    try:
        async with replica(database, monkeypatch, agent) as service:
            await service.invoke(AgentRequest(message="old", user_id="u"))
    finally:
        monkeypatch.undo()
    await rows(database, "DROP TABLE neuron_run_leases")  # e.g. a job that ran before migration 2
    persistence = build_persistence(_settings(database))
    await persistence.open()
    try:
        with structlog.testing.capture_logs() as logs:
            pruned = await prune_threads(
                persistence, older_than=timedelta(days=-1), delete_leases=True
            )
    finally:
        await persistence.close()
    assert pruned == 1
    assert await scalar(database, "SELECT count(*) FROM checkpoints") == 0
    assert any(log["event"] == "run_lease_cleanup_failed" for log in logs)


async def test_lease_table_has_its_indexes_and_kind_check(database: str) -> None:
    for index in ("neuron_run_leases_owner_idx", "neuron_run_leases_expires_idx"):
        assert await scalar(database, "SELECT to_regclass(%s) IS NOT NULL", index) is True
    with pytest.raises(psycopg.errors.CheckViolation):
        await rows(
            database,
            "INSERT INTO neuron_run_leases (owner_key, kind, expires_at)"
            " VALUES ('o', 'bogus', clock_timestamp())",
        )
