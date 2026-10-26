"""The database password never reaches logs or exception text (issue #204)."""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest
from psycopg_pool import PoolTimeout
from pydantic import SecretStr

from neuron_agent.config.settings import Settings
from neuron_agent.persistence import cli
from neuron_agent.persistence.checkpointer import build_persistence
from neuron_agent.persistence.dsn_redaction import DsnRedactionFilter

pytestmark = pytest.mark.anyio

_PASSWORD = "Zq7-distinctive-pw-204"  # noqa: S105 - fake, test only
# libpq rejects this URI and echoes all of it, password included, in the error message.
_MALFORMED_DSN = f"postgresql://neuron:{_PASSWORD}@[::1:5432/neuron"


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.text: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.text.append(self.format(record))


@pytest.fixture
def captured() -> Iterator[_Capture]:
    handler = _Capture()
    root = logging.getLogger()
    previous = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    yield handler
    root.removeHandler(handler)
    root.setLevel(previous)
    for name in ("psycopg", "psycopg.pool"):
        target = logging.getLogger(name)
        for f in [f for f in target.filters if isinstance(f, DsnRedactionFilter)]:
            target.removeFilter(f)


def _settings(dsn: str) -> Settings:
    return Settings(
        env="test",
        checkpointer="postgres",
        postgres_dsn=SecretStr(dsn),
        postgres_pool_timeout_seconds=1,
        openai_api_key=None,
    )


async def test_failed_pool_connect_never_logs_the_password(captured: _Capture) -> None:
    persistence = build_persistence(_settings(_MALFORMED_DSN))
    assert persistence.pool is not None
    errors: list[str] = []
    await persistence.pool.open(wait=False)
    try:
        async with persistence.pool.connection():
            pass
    except PoolTimeout as exc:
        errors.append(repr(exc))
    finally:
        await persistence.pool.close()

    output = "\n".join(captured.text)
    assert "error connecting" in output  # the failure was logged, just without the secret
    assert _PASSWORD not in output
    assert all(_PASSWORD not in e for e in errors)


async def test_unreachable_host_failure_never_logs_the_password(captured: _Capture) -> None:
    persistence = build_persistence(
        _settings(f"postgresql://neuron:{_PASSWORD}@127.0.0.1:1/neuron")
    )
    assert persistence.pool is not None
    await persistence.pool.open(wait=False)
    try:
        with pytest.raises(PoolTimeout):
            async with persistence.pool.connection():
                pass
    finally:
        await persistence.pool.close()
    assert _PASSWORD not in "\n".join(captured.text)


def test_filter_scrubs_message_args_and_exception_text() -> None:
    redactor = DsnRedactionFilter(f"host=h user=u password='{_PASSWORD}'")
    try:
        raise ValueError(f"bad conninfo password={_PASSWORD}")
    except ValueError:
        import sys

        exc_info = sys.exc_info()
    record = logging.LogRecord(
        "psycopg.pool",
        logging.WARNING,
        __file__,
        1,
        "failed: %s",
        (f"://u:{_PASSWORD}@h",),
        exc_info,
    )
    redactor.filter(record)
    rendered = logging.Formatter().format(record)
    assert _PASSWORD not in rendered
    assert "***" in rendered


def test_setup_cli_failure_never_prints_the_password(
    capsys: pytest.CaptureFixture[str], captured: _Capture
) -> None:
    with pytest.raises(SystemExit):
        cli._setup(_settings(_MALFORMED_DSN), rotate_identity_key=False)
    seen = capsys.readouterr()
    assert _PASSWORD not in seen.out + seen.err + "\n".join(captured.text)
