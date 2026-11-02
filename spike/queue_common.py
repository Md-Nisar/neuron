"""Shared by the queue spike workers (RAG-00.02). Throwaway code; never merged."""
import os

import psycopg

APP_DSN = "postgresql://neuron_app:app-local-only@127.0.0.1:55432/neuron"
MIGRATOR_DSN = "postgresql://neuron_migrator:migrator-local-only@127.0.0.1:55432/neuron"
TASK_SECONDS = float(os.environ.get("SPIKE_TASK_SECONDS", "6"))


async def record(lib: str, doc_id: int, phase: str) -> None:
    async with await psycopg.AsyncConnection.connect(APP_DSN, autocommit=True) as conn:
        await conn.execute(
            "INSERT INTO spike_effects (lib, doc_id, pid, phase) VALUES (%s, %s, %s, %s)",
            (lib, doc_id, os.getpid(), phase),
        )
        if phase == "finish":
            # The idempotent write a real ingest task makes: one result per (doc, profile).
            await conn.execute(
                "INSERT INTO spike_done (lib, doc_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (lib, doc_id),
            )


async def failed_before(lib: str, doc_id: int) -> bool:
    async with await psycopg.AsyncConnection.connect(APP_DSN, autocommit=True) as conn:
        cur = await conn.execute(
            "SELECT count(*) FROM spike_effects WHERE lib=%s AND doc_id=%s AND phase='fail'",
            (lib, doc_id),
        )
        row = await cur.fetchone()
        return bool(row and row[0])
