"""App for the two-process Postgres harness (`pg_harness.py`); run by Uvicorn, not by pytest.

The real FastAPI app, with two test-only changes made before it is imported:

- the model is a `ControlledAgent` whose behaviour the request message selects, so a test can
  hold a run (and its lease) open without a model: `hold <seconds>` waits that long,
  `hang` waits forever, anything else answers at once;
- the request rate limiter and the token budget fall back to their in-memory versions. They
  have no Postgres implementation yet (#147, #148), so `APP_LIMITS_BACKEND=postgres` would
  otherwise stop start-up. Delete the matching line here when each lands.
"""

from __future__ import annotations

import asyncio
from typing import Any

from neuron_agent.graphs import main_graph
from neuron_agent.persistence import guards
from neuron_agent.schemas.agent import AgentAnswer


class ControlledAgent:
    async def ainvoke(self, inputs: dict[str, Any], **_: Any) -> dict[str, Any]:
        words = str(inputs["messages"][-1].content).split()
        if words[:1] == ["hold"]:
            await asyncio.sleep(float(words[1]))
        elif words[:1] == ["hang"]:
            await asyncio.Event().wait()
        answer = AgentAnswer(answer="ok", used_tools=[], confidence=1.0)
        return {"messages": [], "structured_response": answer}


setattr(guards, "_require_memory", lambda settings: None)  # noqa: B010 - see the docstring
setattr(main_graph, "build_agent", lambda settings: ControlledAgent())  # noqa: B010

from neuron_agent.api.main import app  # noqa: E402,F401  (imported after the changes above)
