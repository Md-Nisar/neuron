"""Operator commands for thread persistence: `python -m neuron_agent.persistence.cli setup`."""

from __future__ import annotations

import argparse
import asyncio

from neuron_agent.config.settings import get_settings
from neuron_agent.observability.logging import configure_logging
from neuron_agent.persistence.checkpointer import build_persistence


async def _setup() -> None:
    persistence = build_persistence(get_settings())
    await persistence.open(run_setup=True)
    await persistence.close()


def main(argv: list[str] | None = None) -> None:
    """Run a persistence maintenance command."""
    parser = argparse.ArgumentParser(prog="neuron-persistence")
    parser.add_argument("command", choices=["setup"], help="setup: create checkpoint tables")
    args = parser.parse_args(argv)
    settings = get_settings()
    configure_logging(
        level=settings.log_level,
        service=settings.name,
        version=settings.version,
        environment=settings.env,
    )
    if args.command == "setup":
        asyncio.run(_setup())


if __name__ == "__main__":
    main()
