from __future__ import annotations

import os

import pytest

from neuron_agent.config.settings import Settings
from neuron_agent.schemas.agent import AgentRequest
from neuron_agent.services.agent_service import AgentService

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OPENAI_API_KEY is not configured")
async def test_live_openai_streaming_smoke() -> None:
    settings = Settings(
        env="development",
        default_model="openai:gpt-5.4-mini",
        openai_api_key=os.environ["OPENAI_API_KEY"],
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
