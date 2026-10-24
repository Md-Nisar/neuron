# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Operator commands for thread persistence.

python -m neuron_agent.persistence.cli setup [--rotate-identity-key]
python -m neuron_agent.persistence.cli prune [--older-than-days N]

Both are operator-only: there is no HTTP route for either (SECURITY.md). `setup` connects as
the migrator role (`APP_POSTGRES_MIGRATION_DSN`) and `prune` as the app role
(`APP_POSTGRES_DSN`), ADR 0008 decision 15.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import timedelta

import psycopg

from neuron_agent.config.settings import Settings, get_settings
from neuron_agent.observability.logging import configure_logging
from neuron_agent.persistence import migrations
from neuron_agent.persistence.checkpointer import build_persistence
from neuron_agent.persistence.retention import prune_threads
from neuron_agent.persistence.startup_checks import StartupCheckError


class SetupError(Exception):
    """A setup failure whose message is fixed text, safe to print."""


def _migration_dsn(settings: Settings) -> str:
    """The only reader of `postgres_migration_dsn` (a test enforces it).

    Staging and production use it alone; development and test fall back to the runtime DSN.
    """
    dsn = settings.postgres_migration_dsn
    if (dsn is None or not dsn.get_secret_value()) and settings.env in {"staging", "production"}:
        raise SetupError("APP_POSTGRES_MIGRATION_DSN is required in staging and production")
    if dsn is None or not dsn.get_secret_value():
        dsn = settings.postgres_dsn
    if dsn is None or not dsn.get_secret_value():
        raise SetupError("no database configured: set APP_POSTGRES_MIGRATION_DSN")
    return dsn.get_secret_value()


def _describe(exc: Exception) -> str:
    """Name a failure without its text: driver messages can echo hosts and credentials."""
    if isinstance(
        exc,
        SetupError | migrations.LockWaitTimeout | migrations.IdentityKeyMismatch,
    ):
        return str(exc)
    if isinstance(exc, StartupCheckError):
        return f"{exc.code}: {exc}"
    sqlstate = getattr(exc, "sqlstate", None) if isinstance(exc, psycopg.Error) else None
    return type(exc).__name__ + (f" (SQLSTATE {sqlstate})" if sqlstate else "")


def _setup(settings: Settings, *, rotate_identity_key: bool) -> None:
    key = settings.identity_hash_key
    try:
        if rotate_identity_key and (key is None or not key.get_secret_value()):
            raise SetupError("--rotate-identity-key needs APP_IDENTITY_HASH_KEY")
        applied = asyncio.run(
            migrations.run_setup(
                _migration_dsn(settings),
                app_role=settings.postgres_app_role,
                # Production must have the split; staging may run one role (decision 17).
                require_app_role=settings.env == "production",
                identity_hash_key=key.get_secret_value() if key else None,
                rotate_identity_key=rotate_identity_key,
            )
        )
    except Exception as exc:
        # No traceback and no exception text: either could carry the DSN.
        print(f"setup failed: {_describe(exc)}", file=sys.stderr)
        raise SystemExit(1) from None
    print(f"setup complete: applied migrations {applied or 'none'}")


async def _prune(older_than_days: int) -> None:
    settings = get_settings()
    persistence = build_persistence(settings)
    await persistence.open()
    try:
        await prune_threads(
            persistence,
            older_than=timedelta(days=older_than_days),
            delete_leases=settings.limits_backend == "postgres",
            ledger_window_seconds=(
                settings.user_token_budget_window_seconds
                if settings.limits_backend == "postgres"
                else None
            ),
            rate_bucket_idle_seconds=(
                settings.rate_limit_burst
                * settings.rate_limit_window_seconds
                / settings.rate_limit_requests_per_window
                if settings.limits_backend == "postgres"
                else None
            ),
        )
    finally:
        await persistence.close()


def main(argv: list[str] | None = None) -> None:
    """Run a persistence maintenance command."""
    parser = argparse.ArgumentParser(prog="neuron-persistence")
    parser.add_argument(
        "command",
        choices=["setup", "prune"],
        help="setup: create/migrate the schema; prune: delete threads past retention",
    )
    parser.add_argument(
        "--older-than-days",
        type=int,
        default=None,
        help="prune threads inactive for longer than this (default: APP_THREAD_RETENTION_DAYS)",
    )
    parser.add_argument(
        "--rotate-identity-key",
        action="store_true",
        help="setup: replace the stored APP_IDENTITY_HASH_KEY check value (orphans threads)",
    )
    args = parser.parse_args(argv)
    # Validate before any side effects (logging configuration, database connections).
    if args.older_than_days is not None and args.older_than_days < 1:
        parser.error("--older-than-days must be at least 1")
    if args.rotate_identity_key and args.command != "setup":
        parser.error("--rotate-identity-key applies to setup only")
    if args.older_than_days is not None and args.command != "prune":
        parser.error("--older-than-days applies to prune only")
    settings = get_settings()
    configure_logging(
        level=settings.log_level,
        service=settings.name,
        version=settings.version,
        environment=settings.env,
    )
    if args.command == "setup":
        _setup(settings, rotate_identity_key=args.rotate_identity_key)
    elif args.command == "prune":
        try:
            asyncio.run(_prune(args.older_than_days or settings.thread_retention_days))
        except Exception as exc:
            # Same rule as setup: no traceback and no exception text, which can carry the DSN.
            print(f"prune failed: {_describe(exc)}", file=sys.stderr)
            raise SystemExit(1) from None


if __name__ == "__main__":
    main()
