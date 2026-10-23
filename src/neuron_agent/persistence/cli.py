# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Operator commands for thread persistence.

python -m neuron_agent.persistence.cli setup
python -m neuron_agent.persistence.cli prune [--older-than-days N]
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
    if isinstance(exc, SetupError | migrations.LockWaitTimeout):
        return str(exc)
    sqlstate = getattr(exc, "sqlstate", None) if isinstance(exc, psycopg.Error) else None
    return type(exc).__name__ + (f" (SQLSTATE {sqlstate})" if sqlstate else "")


def _setup(settings: Settings) -> None:
    try:
        applied = asyncio.run(migrations.run_setup(_migration_dsn(settings)))
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
    args = parser.parse_args(argv)
    # Validate before any side effects (logging configuration, database connections).
    if args.older_than_days is not None and args.older_than_days < 1:
        parser.error("--older-than-days must be at least 1")
    settings = get_settings()
    configure_logging(
        level=settings.log_level,
        service=settings.name,
        version=settings.version,
        environment=settings.env,
    )
    if args.command == "setup":
        _setup(settings)
    elif args.command == "prune":
        asyncio.run(_prune(args.older_than_days or settings.thread_retention_days))


if __name__ == "__main__":
    main()
