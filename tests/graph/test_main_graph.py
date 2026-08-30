from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from neuron_agent.graphs.main_graph import call_agent
from neuron_agent.schemas.agent import AgentAnswer
from neuron_agent.state.main import MainGraphState

pytestmark = pytest.mark.anyio


class FakeAgent:
    async def ainvoke(
        self, _: dict[str, object], *, config: dict[str, object]
    ) -> dict[str, object]:
        assert config == {"recursion_limit": 5, "timeout": 20}
        return {
            "messages": [AIMessage(content="4")],
            "structured_response": AgentAnswer(
                answer="4", used_tools=["calculator"], confidence=1.0
            ),
        }


async def test_call_agent_uses_structured_response() -> None:
    state: MainGraphState = {
        "messages": [HumanMessage(content="2+2")],
        "request_id": "request-1",
        "thread_id": "thread-1",
    }
    result = await call_agent(state, agent=FakeAgent())
    assert result["answer"].answer == "4"
    assert result["answer"].used_tools == ["calculator"]
