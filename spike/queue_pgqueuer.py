"""PGQueuer 1.6 worker and enqueuer for the kill test. Usage: worker | defer N FIRST."""
import asyncio
import json
import sys
from datetime import timedelta

import psycopg
from pgqueuer.adapters.cli.supervisor import setup_signal_handlers
from pgqueuer import DatabaseRetryEntrypointExecutor, Job, PgQueuer, PsycopgDriver, Queries

from queue_common import APP_DSN, TASK_SECONDS, failed_before, record

HEARTBEAT_TIMEOUT = timedelta(seconds=6)


async def main() -> None:
    conn = await psycopg.AsyncConnection.connect(APP_DSN, autocommit=True)
    driver = PsycopgDriver(conn)
    if sys.argv[1] != "worker":
        n, first = int(sys.argv[2]), int(sys.argv[3])
        queries = Queries(driver)
        for doc_id in range(first, first + n):
            await queries.enqueue("ingest", json.dumps({"doc_id": doc_id}).encode())
        return
    pgq = PgQueuer(driver)

    @pgq.entrypoint(
        "ingest",
        executor_factory=lambda p: DatabaseRetryEntrypointExecutor(
            parameters=p, max_attempts=3, initial_delay=timedelta(seconds=1)
        ),
    )
    async def ingest(job: Job) -> None:
        doc_id = json.loads(job.payload or b"{}")["doc_id"]
        await record("pgqueuer", doc_id, "start")
        if doc_id == 1 and not await failed_before("pgqueuer", doc_id):
            await record("pgqueuer", doc_id, "fail")
            raise RuntimeError("first attempt fails on purpose")
        await asyncio.sleep(TASK_SECONDS)
        await record("pgqueuer", doc_id, "finish")

    setup_signal_handlers(pgq.shutdown)  # what the pgqueuer CLI does
    await pgq.run(heartbeat_timeout=HEARTBEAT_TIMEOUT, dequeue_timeout=timedelta(seconds=2))


asyncio.run(main())
