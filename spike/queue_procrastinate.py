"""Procrastinate 3.10 worker and deferrer for the kill test. Usage: worker | defer N FIRST."""
import asyncio
import sys

import procrastinate

from queue_common import APP_DSN, TASK_SECONDS, failed_before, record

HEARTBEAT, STALLED = 2.0, 6.0
# Neuron's pool settings: APP_POSTGRES_POOL_MAX_SIZE=10, APP_POSTGRES_POOL_TIMEOUT_SECONDS=10.
app = procrastinate.App(
    connector=procrastinate.PsycopgConnector(conninfo=APP_DSN, min_size=1, max_size=10, timeout=10)
)


@app.task(name="ingest", retry=procrastinate.RetryStrategy(max_attempts=3, wait=1))
async def ingest(doc_id: int) -> None:
    await record("procrastinate", doc_id, "start")
    if doc_id == 1 and not await failed_before("procrastinate", doc_id):
        await record("procrastinate", doc_id, "fail")
        raise RuntimeError("first attempt fails on purpose")
    await asyncio.sleep(TASK_SECONDS)
    await record("procrastinate", doc_id, "finish")


@app.periodic(cron="* * * * * */3")
@app.task(name="retry_stalled", queueing_lock="retry_stalled", pass_context=True)
async def retry_stalled(context: procrastinate.JobContext, timestamp: int) -> None:
    # Procrastinate does not re-run a dead worker's job by itself: this sweep is required.
    for job in await context.app.job_manager.get_stalled_jobs(seconds_since_heartbeat=STALLED):
        await context.app.job_manager.retry_job(job)
        await record("procrastinate", -1, f"retried:{job.id}")


async def main() -> None:
    async with app.open_async():
        if sys.argv[1] == "worker":
            await app.run_worker_async(
                concurrency=4, update_heartbeat_interval=HEARTBEAT, stalled_worker_timeout=STALLED
            )
        else:
            n, first = int(sys.argv[2]), int(sys.argv[3])
            for doc_id in range(first, first + n):
                await ingest.defer_async(doc_id=doc_id)


asyncio.run(main())
