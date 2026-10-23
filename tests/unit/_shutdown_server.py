# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""`neuron-api` with a delayed fake agent, for the subprocess shutdown test.

Only the agent is replaced; the server, signal handling, lifespan and routes are the real
ones. A message starting with `stream` takes 60 s (ended by shutdown), any other takes
`NEURON_TEST_RUN_SECONDS`. Each run touches `<NEURON_TEST_MARKER_DIR>/started-<n>` first.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from typing import Any

from neuron_agent.api import main as api_main
from neuron_agent.graphs import main_graph
from neuron_agent.schemas.agent import AgentAnswer

MARKERS = Path(os.environ["NEURON_TEST_MARKER_DIR"])
RUN_SECONDS = float(os.environ["NEURON_TEST_RUN_SECONDS"])


class DelayedAgent:
    async def ainvoke(
        self, inputs: dict[str, Any], *, config: dict[str, Any], context: Any = None
    ) -> dict[str, Any]:
        (MARKERS / f"started-{uuid.uuid4()}").touch()
        slow = str(inputs["messages"][-1].content).startswith("stream")
        await asyncio.sleep(60 if slow else RUN_SECONDS)
        answer = AgentAnswer(answer="finished", used_tools=[], confidence=1.0)
        return {"messages": [], "structured_response": answer}


main_graph.build_agent = lambda settings: DelayedAgent()  # type: ignore[assignment]
api_main.service = api_main.AgentService(api_main.settings)

if __name__ == "__main__":
    api_main.main()
