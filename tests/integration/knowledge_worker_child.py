"""A `neuron-worker` with one extra task that sleeps, for the fault-injection tests.

python knowledge_worker_child.py DONE_FILE   (settings from the environment)
Each completed `sleep` job appends a line to DONE_FILE, so a second completion would show.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from neuron_agent.config.settings import Settings
from neuron_agent.knowledge import worker

settings = Settings()
app = worker.build_app(settings)
done = Path(sys.argv[1])


@app.task(name="sleep", queue=worker.QUEUE, retry=worker.RETRY)
async def sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)
    with done.open("a") as file:
        file.write("done\n")


asyncio.run(worker.run(settings, app))
