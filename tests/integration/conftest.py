from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pg_harness
import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from neuron_agent.persistence.migrations import run_setup

# On Windows, Psycopg async requires the selector event loop rather than proactor.
if sys.platform == "win32":
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

_CONTAINER_NAME: str | None = None


def _docker(*args: str, check: bool = False, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603  # nosec B603
        ["docker", *args],  # noqa: S607  # nosec B607
        capture_output=True,
        text=True,
        timeout=timeout,
        check=check,
    )


def pytest_configure(config: pytest.Config) -> None:
    """Start ephemeral Postgres if APP_TEST_POSTGRES_DSN is unset and Docker is available (#374)."""
    global _CONTAINER_NAME
    # Ensure subprocesses spawned during tests inherit sitecustomize for Windows event loop policy
    integration_dir = str(Path(__file__).parent)
    current_pp = os.environ.get("PYTHONPATH", "")
    if integration_dir not in current_pp.split(os.pathsep):
        os.environ["PYTHONPATH"] = (
            f"{integration_dir}{os.pathsep}{current_pp}" if current_pp else integration_dir
        )

    if os.environ.get("APP_TEST_POSTGRES_DSN"):
        return
    if not shutil.which("docker"):
        return

    name = f"neuron-test-pg-{uuid.uuid4().hex[:8]}"
    try:
        _docker(
            "run",
            "-d",
            "--rm",
            "--name",
            name,
            "-e",
            "POSTGRES_PASSWORD=postgres",
            "-p",
            "127.0.0.1:0:5432",
            "postgres:16",
            check=True,
        )
        port_proc = _docker("port", name, "5432", check=True)
        m = re.search(r":(\d+)$", port_proc.stdout.strip())
        if not m:
            _docker("stop", name)
            return
        port = m.group(1)
        dsn = f"postgresql://postgres:postgres@127.0.0.1:{port}/postgres"

        for _ in range(30):
            ready_proc = _docker("exec", name, "pg_isready", "-U", "postgres", "-d", "postgres")
            if ready_proc.returncode == 0:
                break
            time.sleep(1)
        else:
            _docker("stop", name)
            return

        _CONTAINER_NAME = name
        os.environ["APP_TEST_POSTGRES_DSN"] = dsn
    except Exception:
        _docker("stop", name)


def pytest_unconfigure(config: pytest.Config) -> None:
    """Clean up ephemeral Postgres container at the end of the test session."""
    global _CONTAINER_NAME
    if _CONTAINER_NAME:
        _docker("stop", _CONTAINER_NAME)
        _CONTAINER_NAME = None


@pytest.fixture
async def database(reap_app_processes: None) -> AsyncIterator[str]:
    """A fresh, fully migrated database per test; yields its DSN."""
    dsn = os.environ.get("APP_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip(
            "APP_TEST_POSTGRES_DSN is not set and Docker is unavailable; see OPERATIONS.md."
        )
    name = f"neuron_guard_{uuid.uuid4().hex[:12]}"
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as admin:
        await admin.execute(f'CREATE DATABASE "{name}"')  # nosec B608 - generated name
        try:
            test_dsn = make_conninfo(dsn, dbname=name)
            await run_setup(test_dsn)
            yield test_dsn
        finally:
            await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')  # nosec B608


@pytest.fixture
def echo_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the LLM with an echo model in tests that invoke an agent against the database."""
    pg_harness.stub_main_agent(monkeypatch)


@pytest.fixture(autouse=True)
def reap_app_processes() -> Iterator[None]:
    """Stop any lingering background app processes started by the test harness."""
    yield
    pg_harness.stop_all()
