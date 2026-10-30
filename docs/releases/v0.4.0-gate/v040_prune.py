import asyncio
from datetime import UTC, datetime, timedelta
from neuron_agent.config.settings import Settings
from neuron_agent.persistence.checkpointer import build_persistence
from neuron_agent.persistence.retention import prune_threads

async def main():
    settings = Settings(env="development", checkpointer="postgres",
                        postgres_dsn="postgresql://postgres@/neuron_migration?host=/var/tmp/neuron-pg&port=55432")
    persistence = build_persistence(settings)
    await persistence.open()
    try:
        today = await prune_threads(persistence, older_than=timedelta(days=settings.thread_retention_days))
        later = await prune_threads(persistence, older_than=timedelta(days=settings.thread_retention_days),
                                    now=datetime.now(UTC) + timedelta(days=settings.thread_retention_days + 1))
        print(f"[{'PASS' if (today, later) == (0, 4) else 'FAIL'}] retention ({settings.thread_retention_days} days): "
              f"pruned {today} today, {later} one retention window later (3 v0.3 threads + 1 v0.4 thread)")
    finally:
        await persistence.close()
asyncio.run(main())
