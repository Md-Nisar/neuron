from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage

from neuron_agent.config.settings import Settings
from neuron_agent.graphs.main_graph import build_graph

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


async def test_live_openai_smoke(live_provider: str) -> None:
    settings = Settings(env="development")
    graph = build_graph(settings)
    # The agent node is async, so the graph must be driven through the async API.
    result = await graph.ainvoke(
        {
            "messages": [HumanMessage(content="Reply with exactly: ok")],
            "request_id": "smoke-request",
            "thread_id": "smoke-thread",
            "run_id": "12345678-1234-5678-1234-567812345678",
        }
    )
    answer = result["answer"]
    assert answer.answer.strip().lower() == "ok"
