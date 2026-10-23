"""Shared request rate limiting in Postgres (#148, ADR 0008 decision 8), against a real database.

Limiter-level tests use `PostgresRateLimiter` directly (two pools are two replicas); the HTTP
tests run Uvicorn processes (`pg_harness.py`). The stand-in-limiter tests (key derivation,
proxy handling, the pre-limit, fail closed over HTTP) are in `tests/security/`.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
import structlog.testing
from pg_harness import AppProcess
from psycopg.conninfo import make_conninfo
from pydantic import SecretStr

from neuron_agent.config.settings import Settings
from neuron_agent.errors.base import PersistenceError
from neuron_agent.persistence.checkpointer import build_persistence
from neuron_agent.persistence.guards import build_rate_limiter
from neuron_agent.persistence.rate_limiter import PostgresRateLimiter, delete_idle_buckets
from neuron_agent.persistence.retention import prune_threads
from neuron_agent.security.auth import ip_rate_key
from neuron_agent.security.rate_limiter import InMemoryTokenBucketRateLimiter, RateLimiter

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.anyio]

_ADMIN_DSN = os.environ.get("APP_TEST_POSTGRES_DSN", "")
KEY = "k" * 32
SLOW = {"requests_per_window": 1, "window_seconds": 3600}  # no refill within a test


async def rows(dsn: str, query: str, *params: object) -> list[tuple[Any, ...]]:
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as conn:
        cursor = await conn.execute(query, params)  # type: ignore[call-overload]
        return await cursor.fetchall() if cursor.description else []


async def bucket_count(dsn: str) -> int:
    return int((await rows(dsn, "SELECT count(*) FROM neuron_rate_buckets"))[0][0])


def _settings(dsn: str, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "env": "test",
        "checkpointer": "none",
        "limits_backend": "postgres",
        "postgres_dsn": SecretStr(dsn),
        "identity_hash_key": SecretStr(KEY),
        "openai_api_key": None,
    }
    return Settings(**{**values, **overrides})


@asynccontextmanager
async def limiter_on(
    dsn: str, pool_size: int = 10, **options: Any
) -> AsyncIterator[PostgresRateLimiter]:
    """A limiter on its own pool; two of these are two replicas."""
    persistence = build_persistence(_settings(dsn, postgres_pool_max_size=pool_size))
    await persistence.open()
    assert persistence.pool is not None
    try:
        yield PostgresRateLimiter(persistence.pool, **{"capacity": 5, **SLOW, **options})
    finally:
        await persistence.close()


async def _allowed(limiter: RateLimiter, key: str, times: int) -> int:
    results = await asyncio.gather(*(limiter.check(key) for _ in range(times)))
    return sum(1 for decision in results if decision.allowed)


# --- the bucket ------------------------------------------------------------------------------


async def test_the_table_is_unlogged_and_the_idle_index_exists(database: str) -> None:
    assert await rows(
        database, "SELECT relpersistence FROM pg_class WHERE relname = %s", "neuron_rate_buckets"
    ) == [("u",)]
    assert await rows(
        database,
        "SELECT indisvalid FROM pg_index WHERE indexrelid = %s::regclass",
        "neuron_rate_buckets_refilled_idx",
    ) == [(True,)]


@pytest.fixture(params=["memory", "postgres"])
async def any_limiter(request: pytest.FixtureRequest, database: str) -> AsyncIterator[RateLimiter]:
    if request.param == "memory":
        yield InMemoryTokenBucketRateLimiter(capacity=3, **SLOW)
        return
    async with limiter_on(database, capacity=3) as limiter:
        yield limiter


async def test_burst_then_refusal_with_a_retry_after_on_both_implementations(
    any_limiter: RateLimiter,
) -> None:
    assert [(await any_limiter.check("a")).allowed for _ in range(3)] == [True] * 3
    refused = await any_limiter.check("a")
    assert refused.allowed is False
    assert 0 < refused.retry_after_seconds <= 3600
    assert (await any_limiter.check("b")).allowed is True  # another key is unaffected


async def test_tokens_refill_with_the_database_clock(database: str) -> None:
    async with limiter_on(
        database, capacity=2, requests_per_window=10, window_seconds=1
    ) as limiter:
        assert await _allowed(limiter, "k", 5) == 2
        await asyncio.sleep(0.35)  # 10 per second: three tokens, capped at the capacity of two
        assert [(await limiter.check("k")).allowed for _ in range(3)] == [True, True, False]


async def test_a_burst_split_across_two_replicas_is_limited_to_the_burst_in_total(
    database: str,
) -> None:
    async with limiter_on(database, capacity=10) as one, limiter_on(database, capacity=10) as two:
        granted = await asyncio.gather(_allowed(one, "shared", 30), _allowed(two, "shared", 30))
        assert sum(granted) == 10
        assert await bucket_count(database) == 1

    # The same scenario with the in-memory limiter: each replica grants the full burst.
    memory = [InMemoryTokenBucketRateLimiter(capacity=10, **SLOW) for _ in range(2)]
    assert sum([await _allowed(m, "shared", 30) for m in memory]) == 20


# --- idle rows -----------------------------------------------------------------------------


async def test_idle_rows_are_deleted_opportunistically_so_the_table_stays_bounded(
    database: str,
) -> None:
    options = {"capacity": 1, "requests_per_window": 1, "window_seconds": 1}  # idle after 1 s
    async with limiter_on(database, cleanup_every=5, cleanup_batch=50, **options) as limiter:
        for n in range(400):
            await limiter.check(f"old:{n}")
        assert await bucket_count(database) == 400
        await asyncio.sleep(1.2)  # every bucket has refilled completely
        await limiter.check("hot")
        for n in range(100):  # 20 cleanups of up to 50 rows each
            await limiter.check(f"new:{n}")
        survivors = await rows(
            database, "SELECT key FROM neuron_rate_buckets WHERE starts_with(key, 'old:')"
        )
        assert survivors == []
        assert await bucket_count(database) == 101  # "hot" and the new keys, which are not idle
        assert (await limiter.check("hot")).allowed is False  # live state was not deleted


async def test_the_retention_job_deletes_idle_buckets_and_keeps_recent_ones(
    database: str,
) -> None:
    persistence = build_persistence(_settings(database))
    await persistence.open()
    try:
        limiter = build_rate_limiter(_settings(database), persistence)
        for key in ("idle", "recent", "live"):
            await limiter.check(key)
        await rows(
            database,
            "UPDATE neuron_rate_buckets"
            " SET refilled_at = clock_timestamp() - make_interval(secs => %s) WHERE key = %s",
            2 * 3600,
            "idle",
        )
        await rows(
            database,
            "UPDATE neuron_rate_buckets SET refilled_at = clock_timestamp() - interval '10 minutes'"
            " WHERE key = 'recent'",
        )
        # A job configured with a tiny idle time still keeps what is under the one-hour floor.
        await prune_threads(
            persistence, older_than=timedelta(days=30), rate_bucket_idle_seconds=1.0
        )
    finally:
        await persistence.close()
    keys = {row[0] for row in await rows(database, "SELECT key FROM neuron_rate_buckets")}
    assert keys == {"recent", "live"}


async def test_retention_deletes_more_idle_rows_than_one_batch(database: str) -> None:
    persistence = build_persistence(_settings(database))
    await persistence.open()
    try:
        await rows(
            database,
            "INSERT INTO neuron_rate_buckets SELECT 'idle:' || n, 0, clock_timestamp()"
            " - interval '3 hours', true FROM generate_series(1, 2500) AS n",
        )
        assert persistence.pool is not None
        assert await delete_idle_buckets(persistence.pool, 1.0) == 2500
        assert await bucket_count(database) == 0
    finally:
        await persistence.close()


async def test_a_future_dated_row_is_treated_as_clock_damage_and_a_negative_balance_is_refused(
    database: str,
) -> None:
    options = {"capacity": 2, "requests_per_window": 10, "window_seconds": 1}
    async with limiter_on(database, **options) as limiter:
        assert await _allowed(limiter, "k", 2) == 2
        await rows(
            database,
            "UPDATE neuron_rate_buckets SET refilled_at = clock_timestamp() + interval '1 hour'",
        )
        assert (await limiter.check("k")).allowed is False  # no tokens yet, and no extra ones
        ahead = await rows(
            database,
            "SELECT refilled_at > clock_timestamp() + interval '5 seconds'"
            " FROM neuron_rate_buckets",
        )
        assert ahead == [(False,)]  # reset to the database clock, not left an hour ahead
        await asyncio.sleep(0.35)
        assert (await limiter.check("k")).allowed is True  # refills normally from there
    with pytest.raises(psycopg.errors.CheckViolation):
        await rows(database, "INSERT INTO neuron_rate_buckets VALUES ('neg', -1, now(), true)")


async def test_a_hot_key_cannot_drain_the_pool(database: str) -> None:
    async with limiter_on(database, pool_size=4, lock_timeout_ms=3000, capacity=100) as limiter:
        await limiter.check("hot")
        pool = limiter._pool
        async with await psycopg.AsyncConnection.connect(database) as holder:
            await holder.execute("UPDATE neuron_rate_buckets SET tokens = tokens WHERE key = 'hot'")
            tasks = [asyncio.create_task(limiter.check("hot")) for _ in range(20)]
            await asyncio.sleep(0.3)
            waiting = await rows(
                database,
                "SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock'"
                " AND datname = current_database()",
            )
            assert 1 <= waiting[0][0] <= 2  # the cap is pool size // 2
            async with pool.connection(timeout=1) as conn:  # other work still gets a connection
                await conn.execute("SELECT 1")
            await asyncio.sleep(0.4)  # the rest gave up waiting for a slot
            failed = [t for t in tasks if t.done() and t.exception() is not None]
            assert len(failed) >= 15
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)
        assert all(
            isinstance(o, PersistenceError) or getattr(o, "allowed", False) for o in outcomes
        )


# --- fail closed -----------------------------------------------------------------------------


async def test_a_row_lock_held_past_the_lock_timeout_fails_closed(database: str) -> None:
    async with limiter_on(database, lock_timeout_ms=300) as limiter:
        assert (await limiter.check("k")).allowed is True
        async with await psycopg.AsyncConnection.connect(database) as holder:
            await holder.execute("UPDATE neuron_rate_buckets SET tokens = tokens WHERE key = 'k'")
            started = time.monotonic()
            with structlog.testing.capture_logs():
                with pytest.raises(PersistenceError) as failure:
                    await limiter.check("k")
            assert 0.25 <= time.monotonic() - started < 5
            assert failure.value.context.http_status == 503
            assert failure.value.context.code == "persistence_error"
        assert (await limiter.check("k")).allowed is True


async def test_a_missing_table_fails_closed(database: str) -> None:
    async with limiter_on(database) as limiter:
        await rows(database, "ALTER TABLE neuron_rate_buckets RENAME TO neuron_rate_buckets_off")
        with structlog.testing.capture_logs():
            with pytest.raises(PersistenceError):
                await limiter.check("k")
        await rows(database, "ALTER TABLE neuron_rate_buckets_off RENAME TO neuron_rate_buckets")
        assert (await limiter.check("k")).allowed is True


async def test_an_unreachable_database_is_a_503_over_http_and_recovers(
    database: str, tmp_path: Path
) -> None:
    app = await AppProcess(
        database, tmp_path, "app", **_http_settings(burst=1000, postgres_pool_timeout_seconds=1)
    ).wait_ready()
    try:
        assert (await app.invoke()).status_code == 200
        name = make_conninfo(database).split("dbname=")[1].split()[0]
        async with await psycopg.AsyncConnection.connect(_ADMIN_DSN, autocommit=True) as admin:
            await admin.execute(f'ALTER DATABASE "{name}" ALLOW_CONNECTIONS false')  # nosec B608
            await admin.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s", (name,)
            )
            response = await app.invoke()
            assert (response.status_code, response.json()) == (
                503,
                {"detail": "internal_server_error"},
            )  # persistence_error, hidden; the request never reached the agent
            await admin.execute(f'ALTER DATABASE "{name}" ALLOW_CONNECTIONS true')  # nosec B608
        await _eventually(lambda: _serves(app))
    finally:
        await app.close()


async def _serves(app: AppProcess) -> bool:
    return (await app.invoke()).status_code == 200


async def _eventually(check: Callable[[], Awaitable[bool]], *, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while not await check():
        assert time.monotonic() < deadline, "condition not reached in time"
        await asyncio.sleep(0.2)


# --- two processes ---------------------------------------------------------------------------


def _http_settings(*, burst: int, **extra: Any) -> dict[str, Any]:
    return {
        "rate_limit_enabled": "true",
        "rate_limit_burst": burst,
        "rate_limit_requests_per_window": 1,
        "rate_limit_window_seconds": 3600,
        "identity_hash_key": KEY,
        **extra,
    }


async def _fire(app: AppProcess, times: int) -> list[int]:
    return [r.status_code for r in await asyncio.gather(*(app.invoke() for _ in range(times)))]


async def test_a_burst_split_across_two_processes_is_limited_to_the_burst_in_total(
    database: str, tmp_path: Path
) -> None:
    settings = _http_settings(burst=10)
    one = await AppProcess(database, tmp_path, "one", **settings).wait_ready()
    two = await AppProcess(database, tmp_path, "two", **settings).wait_ready()
    try:
        first, second = await asyncio.gather(_fire(one, 15), _fire(two, 15))
        statuses = first + second
        assert statuses.count(200) == 10
        assert statuses.count(429) == 20
        # The table holds one pseudonymous key for the one client, and no address.
        keys = [row[0] for row in await rows(database, "SELECT key FROM neuron_rate_buckets")]
        assert keys == [ip_rate_key("127.0.0.1", KEY)]
        assert re.fullmatch(r"ip:[0-9a-f]{64}", keys[0])
        assert "127.0.0.1" not in keys[0]
    finally:
        await one.close()
        await two.close()


async def test_the_same_burst_split_across_two_in_memory_processes_is_granted_twice(
    database: str, tmp_path: Path
) -> None:
    settings = _http_settings(burst=10, limits_backend="memory")
    one = await AppProcess(database, tmp_path, "one", **settings).wait_ready()
    two = await AppProcess(database, tmp_path, "two", **settings).wait_ready()
    try:
        first, second = await asyncio.gather(_fire(one, 15), _fire(two, 15))
        assert (first + second).count(200) == 20  # what the shared limiter prevents
    finally:
        await one.close()
        await two.close()


async def test_a_flood_from_one_address_costs_the_database_one_write_per_token_not_per_request(
    database: str, tmp_path: Path
) -> None:
    app = await AppProcess(database, tmp_path, "app", **_http_settings(burst=5)).wait_ready()
    try:
        statuses = [(await app.invoke()).status_code for _ in range(60)]
        assert statuses == [200] * 5 + [429] * 55
        # Row writes as the database counts them (statistics are flushed about once a second).
        query = (
            "SELECT n_tup_ins + n_tup_upd FROM pg_stat_user_tables"
            " WHERE relname = 'neuron_rate_buckets'"
        )
        deadline = time.monotonic() + 15
        writes = 0
        while writes < 5 and time.monotonic() < deadline:
            await asyncio.sleep(0.5)
            writes = int((await rows(database, query))[0][0])
        await asyncio.sleep(1.5)
        assert int((await rows(database, query))[0][0]) == 5  # not 60
    finally:
        await app.close()
