from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator, Iterator

import pg_harness
import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from neuron_agent.persistence.migrations import run_setup

_DSN = os.environ.get("APP_TEST_POSTGRES_DSN")


@pytest.fixture
async def database(reap_app_processes: None) -> AsyncIterator[str]:
    """A fresh, fully migrated database per test; yields its DSN."""
    if not _DSN:
        pytest.skip("APP_TEST_POSTGRES_DSN is not set; see OPERATIONS.md for a local Postgres.")
    name = f"neuron_guard_{uuid.uuid4().hex[:12]}"
    async with await psycopg.AsyncConnection.connect(_DSN, autocommit=True) as admin:
        await admin.execute(f'CREATE DATABASE "{name}"')  # nosec B608 - generated name
        try:
            dsn = make_conninfo(_DSN, dbname=name)
            await run_setup(dsn)
            yield dsn
        finally:
            await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')  # nosec B608


@pytest.fixture
def reap_app_processes() -> Iterator[None]:
    """Stop every app process a test started, however the test ended.

    Synchronous and not autouse: the `database` fixture requests it, so it applies to the
    harness tests only, and the sync Docker layout tests never see it.
    """
    yield
    while pg_harness.LIVE:
        pg_harness.LIVE.pop().stop_now()
