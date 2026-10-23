from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import SecretStr
from tests.conftest import PRODUCTION_PROFILE

from neuron_agent.config.settings import Settings
from neuron_agent.persistence import cli, migrations
from neuron_agent.persistence.migrations import MIGRATIONS, Migration

_RELEASE = re.compile(r"\d+\.\d+\.\d+")
_IDENT = r'(?:"[^"]+"|\w+)'
_UNSAFE = [
    ("DROP", r"\bDROP\b"),
    ("TRUNCATE", r"\bTRUNCATE\b"),
    ("RENAME", r"\bRENAME\b"),
    ("ALTER ... TYPE", rf"\bALTER\s+(?:COLUMN\s+)?{_IDENT}\s+(?:SET\s+DATA\s+)?TYPE\b"),
    ("SET NOT NULL", r"\bSET\s+NOT\s+NULL\b"),
    ("SET LOGGED/UNLOGGED", r"\bSET\s+(?:UN)?LOGGED\b"),
    ("ADD CONSTRAINT without NOT VALID", r"\bADD\s+CONSTRAINT\b(?![^;]*\bNOT\s+VALID\b)"),
    ("CREATE INDEX without CONCURRENTLY", r"\bCREATE\s+(UNIQUE\s+)?INDEX\b(?!\s+CONCURRENTLY\b)"),
]
_ADD = r"\bADD\s+(?:COLUMN\s+)?(?!CONSTRAINT\b|PRIMARY\b|UNIQUE\b|CHECK\b|FOREIGN\b)[^,;]*"


def normalize(sql: str) -> str:
    """Drop comments and collapse whitespace, so they cannot hide a construct."""
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    sql = re.sub(r"--[^\n]*", " ", sql)
    return re.sub(r"\s+", " ", sql).strip()


def violations(sql: str) -> list[str]:
    """Expand/contract rule (ADR 0008 decision 7): names each unsafe construct in `sql`."""
    sql = normalize(sql)
    found = [name for name, pattern in _UNSAFE if re.search(pattern, sql, re.I)]
    for column in re.finditer(_ADD, sql, re.I):
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
        ("TRUNCATE t", "TRUNCATE"),
        ("ALTER TABLE t SET LOGGED", "SET LOGGED/UNLOGGED"),
        ("ALTER TABLE t SET UNLOGGED", "SET LOGGED/UNLOGGED"),
        # Bypass attempts: comments, odd whitespace, optional COLUMN, quoted identifiers.
        ("DROP/* x */TABLE t", "DROP"),
        ("ALTER TABLE t ALTER a TYPE bigint", "ALTER ... TYPE"),
        ("ALTER TABLE t ALTER COLUMN a SET DATA TYPE bigint", "ALTER ... TYPE"),
        ('ALTER TABLE t ALTER COLUMN "a b" TYPE bigint', "ALTER ... TYPE"),
        ("ALTER TABLE t ADD a int NOT NULL", "ADD COLUMN ... NOT NULL without a default"),
        (
            'ALTER TABLE "t" ADD COLUMN "a" int NOT NULL',
            "ADD COLUMN ... NOT NULL without a default",
        ),
        (
            "ALTER TABLE t\n  ADD\n  COLUMN a int\n NOT\tNULL",
            "ADD COLUMN ... NOT NULL without a default",
        ),
        ("ALTER TABLE t -- harmless\n RENAME TO u", "RENAME"),
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
        "ALTER TABLE t ADD CONSTRAINT c CHECK (a IS NOT NULL) NOT VALID",
        "-- DROP the old way later\nCREATE TABLE t (a int) /* TRUNCATE */",
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


def test_migration_flags_are_consistent() -> None:
    for migration in MIGRATIONS:
        assert migration.concurrent == bool(re.search(r"\bCONCURRENTLY\b", migration.sql, re.I))
        if migration.concurrent and re.search(
            r"\bCREATE\s+(UNIQUE\s+)?INDEX\b", migration.sql, re.I
        ):
            assert migration.index, migration.name
        if migration.index:
            # `to_regclass` and DROP INDEX use it as given: lowercase, no schema prefix.
            assert re.fullmatch(r"[a-z_][a-z0-9_]*", migration.index), migration.name


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


# --- least-privilege roles (#144) ----------------------------------------------------------


def _grant_sql() -> list[str]:
    statements = [
        *migrations.default_privilege_statements("migrator_x", "public", "app_x"),
        *migrations.table_grant_statements("public", "app_x"),
    ]
    return [statement.as_string(None) for statement in statements]


def test_grants_are_expand_only_and_dml_only() -> None:
    rendered = _grant_sql()
    assert rendered
    for statement in rendered:
        assert violations(statement) == [], statement
        if statement.startswith(("GRANT", "ALTER DEFAULT")):
            assert not re.search(
                r"\b(CREATE|DROP|TRUNCATE|REFERENCES|TRIGGER|ALL|OWNER|TEMP|TEMPORARY)\b",
                statement,
                re.I,
            ), statement
    assert "app_x" in " ".join(rendered)


def test_identity_check_value_is_an_hmac_of_a_fixed_label() -> None:
    key = "k" * 40
    value = migrations.identity_check_value(key)
    assert value == migrations.identity_check_value(key)
    assert value != migrations.identity_check_value("j" * 40)
    assert key not in value and len(value) == 64


@pytest.mark.parametrize("name", ["Neuron", "neuron app", "1app", 'app"x', "", "a" * 64])
def test_app_role_setting_rejects_unsafe_names(name: str) -> None:
    with pytest.raises(ValueError, match="postgres_app_role"):
        Settings(env="test", postgres_app_role=name)


@pytest.mark.parametrize(("env", "required"), [("staging", False), ("production", True)])
def test_setup_passes_the_role_and_key_and_requires_the_split_in_production(
    env: str, required: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, object] = {}

    async def fake_run_setup(dsn: str, **kwargs: object) -> list[int]:
        seen.update(kwargs)
        return []

    monkeypatch.setattr(migrations, "run_setup", fake_run_setup)
    _use(
        monkeypatch,
        Settings.model_construct(
            env=env,
            postgres_dsn=None,
            postgres_migration_dsn=SecretStr("postgresql://m:p@h/d"),
            postgres_app_role="neuron_app",
            identity_hash_key=SecretStr("k" * 40),
        ),
    )
    cli.main(["setup", "--rotate-identity-key"])
    assert seen == {
        "app_role": "neuron_app",
        "require_app_role": required,
        "identity_hash_key": "k" * 40,
        "rotate_identity_key": True,
    }


def test_rotation_needs_a_key_and_applies_to_setup_only(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _use(
        monkeypatch,
        Settings.model_construct(
            env="development",
            postgres_dsn=SecretStr("postgresql://u:p@h/d"),
            postgres_migration_dsn=None,
            identity_hash_key=None,
        ),
    )
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["setup", "--rotate-identity-key"])
    assert exit_info.value.code == 1
    assert "needs APP_IDENTITY_HASH_KEY" in capsys.readouterr().err
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["prune", "--rotate-identity-key"])
    assert exit_info.value.code == 2


def test_identity_mismatch_message_has_no_key_or_check_value(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    key = "secret-identity-key-" + "k" * 30

    async def refuse(dsn: str, **kwargs: object) -> list[int]:
        raise migrations.IdentityKeyMismatch("differs; pass --rotate-identity-key")

    monkeypatch.setattr(migrations, "run_setup", refuse)
    _use(
        monkeypatch,
        Settings.model_construct(
            env="staging",
            postgres_dsn=None,
            postgres_migration_dsn=SecretStr("postgresql://m:p@h/d"),
            postgres_app_role="neuron_app",
            identity_hash_key=SecretStr(key),
        ),
    )
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["setup"])
    assert exit_info.value.code == 1
    err = capsys.readouterr().err
    assert "--rotate-identity-key" in err
    assert key not in err and migrations.identity_check_value(key) not in err


def _production(**overrides: object) -> Settings:
    return Settings(
        env="production",
        auth_mode="jwt",
        auth_issuer="https://issuer.example.test",
        auth_audience="neuron-api",
        auth_jwks_url="https://issuer.example.test/.well-known/jwks.json",
        identity_hash_key=SecretStr("x" * 32),
        openai_api_key=SecretStr("sk-test"),
        **{**PRODUCTION_PROFILE, "checkpointer": "postgres", **overrides},
    )


def test_production_refuses_one_database_user_for_runtime_and_migrations() -> None:
    same = {
        "postgres_dsn": SecretStr("postgresql://neuron:runtime-pw-1@h/db?sslmode=verify-full"),
        "postgres_migration_dsn": SecretStr(
            "postgresql://neuron:migrate-pw-2@h2/db?sslmode=verify-full"
        ),
    }
    with pytest.raises(ValueError, match="different database users") as caught:
        _production(**same)
    for text in ("runtime-pw-1", "migrate-pw-2", "neuron:", "h2"):
        assert text not in str(caught.value)
    _production(
        postgres_dsn=SecretStr("postgresql://neuron_app:a@h/db?sslmode=verify-full"),
        postgres_migration_dsn=SecretStr("postgresql://neuron_migrator:b@h/db?sslmode=verify-full"),
    )
    # Staging may run one role (ADR 0008 decision 17).
    Settings(
        **{**PRODUCTION_PROFILE, "env": "staging", "checkpointer": "postgres", **same},
        openai_api_key=SecretStr("k"),
        auth_mode="jwt",
        auth_issuer="https://i.example.test",
        auth_audience="a",
        auth_jwks_url="https://i.example.test/j",
        identity_hash_key=SecretStr("x" * 32),
    )


def test_production_dsn_errors_do_not_echo_a_malformed_dsn() -> None:
    with pytest.raises(ValueError, match="is not valid") as caught:
        _production(
            postgres_dsn=SecretStr("postgresql://u:leaky-pw@[bad/db"),
            postgres_migration_dsn=SecretStr("postgresql://m:p@h/db?sslmode=verify-full"),
        )
    assert "leaky-pw" not in str(caught.value)


@pytest.mark.parametrize("name", ["pg_monitor", "pg_", "pg_write_all_data"])
def test_app_role_setting_rejects_pg_prefixed_names(name: str) -> None:
    with pytest.raises(ValueError, match="postgres_app_role"):
        Settings(env="test", postgres_app_role=name)


def test_older_than_days_applies_to_prune_only(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _use(monkeypatch, Settings.model_construct(env="development"))
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["setup", "--older-than-days", "5"])
    assert exit_info.value.code == 2
    assert "prune only" in capsys.readouterr().err


def test_prune_errors_are_fixed_text(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def boom(days: int) -> None:
        raise RuntimeError("postgresql://u:leaky-pw@10.0.0.9/db refused")

    monkeypatch.setattr(cli, "_prune", boom)
    _use(monkeypatch, Settings.model_construct(env="development", thread_retention_days=30))
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["prune"])
    assert exit_info.value.code == 1
    captured = capsys.readouterr()
    assert "prune failed: RuntimeError" in captured.err
    assert "leaky-pw" not in captured.err + captured.out
    assert "Traceback" not in captured.err
