from __future__ import annotations

import uuid

import pytest
import structlog
from langchain_core.messages import HumanMessage

from neuron_agent.config.settings import Settings
from neuron_agent.schemas.agent import AgentAnswer, AgentRequest
from neuron_agent.services.agent_service import AgentService

pytestmark = pytest.mark.anyio


class _FakeGraph:
    def __init__(self) -> None:
        self.last_state: dict[str, object] | None = None
        self.last_config: dict[str, object] | None = None

    async def ainvoke(
        self, state: dict[str, object], *, config: dict[str, object]
    ) -> dict[str, object]:
        self.last_state = state
        self.last_config = config
        return {"answer": AgentAnswer(answer="ok", used_tools=[], confidence=1.0)}


async def test_invoke_binds_and_propagates_a_run_id(monkeypatch: pytest.MonkeyPatch) -> None:
    structlog.contextvars.clear_contextvars()
    settings = Settings(env="test", openai_api_key=None)
    monkeypatch.setattr(
        "neuron_agent.services.agent_service.build_graph", lambda settings: _FakeGraph()
    )
    service = AgentService(settings)

    await service.invoke(AgentRequest(message="hi"))

    graph = service._graph
    assert isinstance(graph, _FakeGraph)
    assert graph.last_state is not None
    run_id = graph.last_state["run_id"]
    uuid.UUID(run_id)  # raises if not a valid UUID string
    assert graph.last_config == {
        "configurable": {"thread_id": graph.last_state["thread_id"]},
        "run_id": uuid.UUID(run_id),
    }
    assert structlog.contextvars.get_contextvars()["run_id"] == run_id
    assert graph.last_state["messages"] == [HumanMessage(content="hi")]
