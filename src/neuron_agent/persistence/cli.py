# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Operator commands for thread persistence.

python -m neuron_agent.persistence.cli setup [--rotate-identity-key]
python -m neuron_agent.persistence.cli prune [--older-than-days N]
python -m neuron_agent.persistence.cli reindex start|status|cancel
python -m neuron_agent.persistence.cli feedback-report

All are operator-only: there is no HTTP route for any (SECURITY.md). `setup` and `reindex`
connect as the migrator role (`APP_POSTGRES_MIGRATION_DSN`) and `prune` as the app role
(`APP_POSTGRES_DSN`), ADR 0008 decision 15. `reindex` moves the knowledge index to the
`APP_KNOWLEDGE_REINDEX_EMBEDDING_*` model (RAG-09.04, ADR 0014). `feedback-report` connects as
the app role and prints, as JSON, the chunk IDs cited by thumbs-down answers (RAG-09.07).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import timedelta

import psycopg

from neuron_agent.config.settings import Settings, get_settings
from neuron_agent.observability.logging import configure_logging
from neuron_agent.persistence import migrations, reindex
from neuron_agent.persistence.checkpointer import (
    build_persistence,
    knowledge_profile,
    knowledge_reindex_profile,
)
from neuron_agent.persistence.feedback_report import negative_feedback_report
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
        SetupError
        | migrations.LockWaitTimeout
        | migrations.IdentityKeyMismatch
        | reindex.ReindexError,
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
                memory_store=settings.memory_enabled,
                knowledge=settings.knowledge_enabled,
                knowledge_profile=knowledge_profile(settings),
                worker_role=settings.postgres_worker_role,
                knowledge_reindex_profile=knowledge_reindex_profile(settings),
            )
        )
    except Exception as exc:
        # No traceback and no exception text: either could carry the DSN.
        print(f"setup failed: {_describe(exc)}", file=sys.stderr)
        raise SystemExit(1) from None
    print(f"setup complete: applied migrations {applied or 'none'}")


def _reindex(settings: Settings, action: str) -> None:
    try:
        if not settings.knowledge_enabled:
            raise SetupError("the knowledge engine is off: set APP_KNOWLEDGE_ENABLED")
        dsn = _migration_dsn(settings)
        if action == "start":
            target = knowledge_reindex_profile(settings)
            if target is None:
                raise SetupError("set APP_KNOWLEDGE_REINDEX_EMBEDDING_* to the target model")
            new = asyncio.run(
                reindex.start(
                    dsn,
                    target,
                    settings.knowledge_reindex_embedding_locality,
                    settings.knowledge_processing_policy,
                )
            )
            print(f"re-index started: profile {new} is building")
        elif action == "status":
            progress = asyncio.run(reindex.status(dsn))
            if progress.profile_id is None:
                print(f"no re-index running; active profile {progress.active}")
            else:
                print(
                    f"profile {progress.profile_id} building (active {progress.active}):"
                    f" {progress.covered}/{progress.chunks} chunks embedded,"
                    f" {progress.bases} bases, {progress.jobs} jobs queued or running"
                )
        else:
            cancelled = asyncio.run(reindex.cancel(dsn))
            print("no re-index running" if cancelled is None else f"profile {cancelled} retired")
    except Exception as exc:
        print(f"reindex {action} failed: {_describe(exc)}", file=sys.stderr)
        raise SystemExit(1) from None


async def _prune(older_than_days: int) -> None:
    settings = get_settings()
    persistence = build_persistence(settings)
    await persistence.open()
    try:
        if persistence.store is not None and settings.memory_ttl_days:
            from neuron_agent.memory.store import MemoryStore, memory_id_key

            await MemoryStore(
                persistence.store,
                id_key=memory_id_key(settings),
                max_items=settings.memory_max_items,
                max_chars=settings.memory_max_chars,
                ttl_days=settings.memory_ttl_days,
            ).purge_expired()
        run_guard = None
        if persistence.pool is not None and settings.limits_backend == "postgres":
            from neuron_agent.persistence.run_guard import PostgresRunGuard

            run_guard = PostgresRunGuard(
                persistence.pool,
                max_concurrent_streams=settings.max_concurrent_streams,
                max_concurrent_runs_per_user=settings.max_concurrent_runs_per_user,
                run_timeout_seconds=settings.run_timeout_seconds,
            )
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
            run_guard=run_guard,
        )
    finally:
        await persistence.close()


def _print_feedback_report(settings: Settings) -> None:
    try:
        if settings.checkpointer != "postgres":
            raise SetupError("feedback-report needs APP_CHECKPOINTER=postgres")
        report = asyncio.run(_feedback_report(settings))
    except Exception as exc:
        print(f"feedback-report failed: {_describe(exc)}", file=sys.stderr)
        raise SystemExit(1) from None
    print(json.dumps(report, indent=2))


async def _feedback_report(settings: Settings) -> dict[str, object]:
    persistence = build_persistence(settings)
    await persistence.open()
    try:
        return await negative_feedback_report(persistence)
    finally:
        await persistence.close()


def main(argv: list[str] | None = None) -> None:
    """Run a persistence maintenance command."""
    parser = argparse.ArgumentParser(prog="neuron-persistence")
    parser.add_argument(
        "command",
        choices=["setup", "prune", "reindex", "feedback-report"],
        help="setup: create/migrate the schema; prune: delete threads past retention;"
        " reindex: move the knowledge index to a new embedding model;"
        " feedback-report: chunk IDs cited by thumbs-down answers",
    )
    parser.add_argument(
        "action",
        nargs="?",
        choices=["start", "status", "cancel"],
        help="reindex: start, report on or cancel a re-index",
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
    if (args.action is None) == (args.command == "reindex"):
        parser.error("reindex needs start, status or cancel; the other commands take none")
    settings = get_settings()
    configure_logging(
        level=settings.log_level,
        service=settings.name,
        version=settings.version,
        environment=settings.env,
    )
    if args.command == "setup":
        _setup(settings, rotate_identity_key=args.rotate_identity_key)
    elif args.command == "reindex":
        _reindex(settings, args.action)
    elif args.command == "prune":
        try:
            asyncio.run(_prune(args.older_than_days or settings.thread_retention_days))
        except Exception as exc:
            # Same rule as setup: no traceback and no exception text, which can carry the DSN.
            print(f"prune failed: {_describe(exc)}", file=sys.stderr)
            raise SystemExit(1) from None
    elif args.command == "feedback-report":
        _print_feedback_report(settings)


if __name__ == "__main__":
    main()
