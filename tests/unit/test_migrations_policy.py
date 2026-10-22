from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import SecretStr

from neuron_agent.config.settings import Settings
from neuron_agent.persistence import cli
from neuron_agent.persistence.migrations import MIGRATIONS, Migration

_RELEASE = re.compile(r"\d+\.\d+\.\d+")
_UNSAFE = [
    ("DROP", r"\bDROP\b"),
    ("RENAME", r"\bRENAME\b"),
    ("ALTER ... TYPE", r"\bALTER\s+COLUMN\s+\w+\s+(SET\s+DATA\s+)?TYPE\b"),
    ("SET NOT NULL", r"\bSET\s+NOT\s+NULL\b"),
    ("ADD CONSTRAINT without NOT VALID", r"\bADD\s+CONSTRAINT\b(?![^;]*\bNOT\s+VALID\b)"),
    ("CREATE INDEX without CONCURRENTLY", r"\bCREATE\s+(UNIQUE\s+)?INDEX\b(?!\s+CONCURRENTLY\b)"),
]


def violations(sql: str) -> list[str]:
    """Expand/contract rule (ADR 0008 decision 7): names each unsafe construct in `sql`."""
    found = [name for name, pattern in _UNSAFE if re.search(pattern, sql, re.I)]
    for column in re.finditer(r"\bADD\s+COLUMN\b[^,;]*", sql, re.I):
        text = column.group(0)
        if re.search(r"\bNOT\s+NULL\b", text, re.I) and not re.search(r"\bDEFAULT\b", text, re.I):
            found.append("ADD COLUMN ... NOT NULL without a default")
    return found


def check(migration: Migration) -> list[str]:
    found = violations(migration.sql)
    if not found or (migration.contract_release and _RELEASE.fullmatch(migration.contract_release)):
        return []
    return found


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ("DROP TABLE t", "DROP"),
        ("ALTER TABLE t RENAME COLUMN a TO b", "RENAME"),
        ("ALTER TABLE t ALTER COLUMN a TYPE bigint", "ALTER ... TYPE"),
        ("ALTER TABLE t ADD COLUMN a int NOT NULL", "ADD COLUMN ... NOT NULL without a default"),
        ("ALTER TABLE t ALTER COLUMN a SET NOT NULL", "SET NOT NULL"),
        ("ALTER TABLE t ADD CONSTRAINT c CHECK (a > 0)", "ADD CONSTRAINT without NOT VALID"),
        ("CREATE INDEX i ON t (a)", "CREATE INDEX without CONCURRENTLY"),
        ("CREATE UNIQUE INDEX i ON t (a)", "CREATE INDEX without CONCURRENTLY"),
    ],
)
def test_unsafe_sql_is_detected_and_needs_a_contract_marker(sql: str, expected: str) -> None:
    assert expected in violations(sql)
    assert check(Migration(version=9, name="x", sql=sql)) != []
    assert check(Migration(version=9, name="x", sql=sql, contract_release="0.7.0")) == []
    assert check(Migration(version=9, name="x", sql=sql, contract_release="soon")) != []


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TABLE t (a int)",
        "ALTER TABLE t ADD COLUMN a int",
        "ALTER TABLE t ADD COLUMN a int NOT NULL DEFAULT 0",
        "ALTER TABLE t ADD CONSTRAINT c CHECK (a > 0) NOT VALID",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS i ON t (a)",
    ],
)
def test_expand_steps_pass(sql: str) -> None:
    assert violations(sql) == []


def test_shipped_migrations_follow_the_compatibility_rule() -> None:
    assert [m.version for m in MIGRATIONS] == list(range(1, len(MIGRATIONS) + 1))
    for migration in MIGRATIONS:
        assert check(migration) == [], migration.name
        if migration.concurrent:
            assert migration.sql.count(";") == 0, "a concurrent migration is one statement"


def test_only_the_cli_reads_the_migration_dsn() -> None:
    allowed = {
        Path("src/neuron_agent/persistence/cli.py"),
        Path("src/neuron_agent/config/settings.py"),  # declares the field
    }
    readers = {
        path
        for path in Path("src").rglob("*.py")
        if "postgres_migration_dsn" in path.read_text("utf-8")
    }
    assert readers == allowed


def _use(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "configure_logging", lambda **_: None)


@pytest.mark.parametrize("env", ["staging", "production"])
def test_setup_requires_the_migration_dsn_outside_development(
    env: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runtime = "postgresql://app:runtime-secret@localhost/db"
    _use(
        monkeypatch,
        Settings.model_construct(
            env=env, postgres_dsn=SecretStr(runtime), postgres_migration_dsn=None
        ),
    )
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["setup"])
    assert exit_info.value.code == 1
    err = capsys.readouterr().err
    assert "APP_POSTGRES_MIGRATION_DSN is required" in err
    assert "runtime-secret" not in err


def test_development_falls_back_to_the_runtime_dsn() -> None:
    settings = Settings.model_construct(
        env="development",
        postgres_dsn=SecretStr("postgresql://u:p@h/d"),
        postgres_migration_dsn=None,
    )
    assert cli._migration_dsn(settings) == "postgresql://u:p@h/d"


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://neuron:wrong-pass-123@127.0.0.1:1/db?connect_timeout=2",
        "not a dsn wrong-pass-123",
        "postgresql://neuron:wrong-pass-123@[bad/db",
    ],
)
def test_cli_errors_never_print_the_dsn_or_password(
    dsn: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _use(
        monkeypatch,
        Settings.model_construct(
            env="production", postgres_dsn=None, postgres_migration_dsn=SecretStr(dsn)
        ),
    )
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["setup"])
    assert exit_info.value.code == 1
    captured = capsys.readouterr()
    assert "setup failed:" in captured.err
    for text in (captured.out, captured.err):
        assert "wrong-pass-123" not in text
        assert "127.0.0.1" not in text
        assert "Traceback" not in text


@pytest.mark.parametrize("env", ["staging", "production"])
def test_startup_setup_is_refused_in_staging_and_production(env: str) -> None:
    with pytest.raises(ValueError, match="SETUP_ON_STARTUP"):
        Settings(
            env=env,
            checkpointer="none",
            checkpointer_setup_on_startup=True,
            openai_api_key=SecretStr("k"),
        )
