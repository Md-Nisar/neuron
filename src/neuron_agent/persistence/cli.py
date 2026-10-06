"""Operator commands for thread persistence.

python -m neuron_agent.persistence.cli setup
python -m neuron_agent.persistence.cli prune [--older-than-days N]
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import timedelta

from neuron_agent.config.settings import get_settings
from neuron_agent.observability.logging import configure_logging
from neuron_agent.persistence.checkpointer import build_persistence
from neuron_agent.persistence.retention import prune_threads


async def _setup() -> None:
    persistence = build_persistence(get_settings())
    await persistence.open(run_setup=True)
    await persistence.close()


async def _prune(older_than_days: int) -> None:
    persistence = build_persistence(get_settings())
    await persistence.open()
    try:
        await prune_threads(persistence, older_than=timedelta(days=older_than_days))
    finally:
        await persistence.close()


def main(argv: list[str] | None = None) -> None:
    """Run a persistence maintenance command."""
    parser = argparse.ArgumentParser(prog="neuron-persistence")
    parser.add_argument(
        "command",
        choices=["setup", "prune"],
        help="setup: create checkpoint tables; prune: delete threads past retention",
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
        asyncio.run(_setup())
    elif args.command == "prune":
        asyncio.run(_prune(args.older_than_days or settings.thread_retention_days))


if __name__ == "__main__":
    main()
