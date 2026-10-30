from __future__ import annotations

import pytest

from neuron_agent.config.settings import Settings
from neuron_agent.schemas.agent import AgentRequest
from neuron_agent.services.agent_service import AgentService

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


async def test_live_openai_streaming_smoke(live_provider: str) -> None:
    settings = Settings(
        env="development",
        checkpointer="memory",
    )
    service = AgentService(settings)
    run = await service.prepare(AgentRequest(message="Reply with exactly: ok"), streaming=True)
    events = [event async for event in service.stream(run)]

    names = [event.event for event in events]
    assert names[0] == "run_started" and names[-2:] == ["final", "done"]
    assert "token" in names, "the live model should stream at least one answer token"
    tokens = "".join(e.data["text"] for e in events if e.event == "token")
    assert events[-2].data["answer"].strip().lower() == "ok"
    assert tokens.strip().lower() == "ok"
