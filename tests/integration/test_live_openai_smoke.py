from __future__ import annotations

import os

import pytest
from langchain_core.messages import HumanMessage

from neuron_agent.config.settings import Settings
from neuron_agent.graphs.main_graph import build_graph

pytestmark = pytest.mark.integration


@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OPENAI_API_KEY is not configured")
def test_live_openai_smoke() -> None:
    settings = Settings(
        env="development",
        default_model="openai:gpt-5.4-mini",
        openai_api_key=os.environ["OPENAI_API_KEY"],
    )
    graph = build_graph(settings)
    result = graph.invoke(
        {
            "messages": [HumanMessage(content="Reply with exactly: ok")],
            "request_id": "smoke-request",
            "thread_id": "smoke-thread",
        }
    )
    answer = result["answer"]
    assert answer.answer.strip().lower() == "ok"
