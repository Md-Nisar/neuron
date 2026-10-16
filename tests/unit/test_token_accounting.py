from __future__ import annotations

from typing import Any

import pytest
import structlog.testing
from langchain.agents.middleware import ModelRequest, ModelResponse
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.runtime import Runtime

from neuron_agent.config.settings import Settings
from neuron_agent.graphs import main_graph
from neuron_agent.models.factory import tool_authorization_middleware
from neuron_agent.schemas.agent import AgentAnswer, AgentRequest
from neuron_agent.security.authorization import (
    AuthorizationContext,
    TokenCounts,
    TokenUsageAccumulator,
)
from neuron_agent.services.agent_service import AgentService

FULL = {
    "input_tokens": 120,
    "output_tokens": 30,
    "total_tokens": 150,
    "input_token_details": {"cache_read": 100},
    "output_token_details": {"reasoning": 12},
}


def test_records_every_kind_summed_over_calls_by_model() -> None:
    usage = TokenUsageAccumulator()
    usage.record(FULL, "model-a")
    usage.record(FULL, "model-a")
    usage.record({"input_tokens": 5, "output_tokens": 1, "total_tokens": 6}, "model-b")

    assert usage.total_tokens == 306
    assert usage.by_model["model-a"] == TokenCounts(300, 240, 60, 200, 24)
    assert usage.by_model["model-b"] == TokenCounts(6, 5, 1, 0, 0)
    assert usage.totals() == TokenCounts(306, 245, 61, 200, 24)


def test_missing_kinds_stay_zero() -> None:
    usage = TokenUsageAccumulator()
    usage.record({"input_tokens": 7, "output_tokens": 3, "total_tokens": 10}, "m")

    assert usage.totals() == TokenCounts(10, 7, 3, 0, 0)


def test_total_only_provider_still_charges_the_total() -> None:
    usage = TokenUsageAccumulator()
    usage.record({"total_tokens": 42})

    assert usage.total_tokens == 42
    assert usage.totals() == TokenCounts(total_tokens=42)
    assert list(usage.by_model) == ["unknown"]


def test_total_is_derived_when_missing_and_junk_is_ignored() -> None:
    usage = TokenUsageAccumulator()
    usage.record({"input_tokens": 4, "output_tokens": 2})
    usage.record({"input_tokens": True, "output_tokens": -3, "input_token_details": "x"})
    usage.record(None)
    usage.record({})

    assert usage.total_tokens == 6
    assert usage.totals() == TokenCounts(6, 4, 2, 0, 0)


@pytest.mark.anyio
async def test_middleware_records_the_response_model() -> None:
    usage = TokenUsageAccumulator()
    request = ModelRequest(
        model=FakeListChatModel(responses=["ok"]),
        messages=[],
        tools=[],
        runtime=Runtime(context=AuthorizationContext(frozenset(), usage=usage)),
    )

    async def handler(_: ModelRequest[object]) -> ModelResponse:
        return ModelResponse(
            result=[
                AIMessage(
                    content="ok", usage_metadata=FULL, response_metadata={"model_name": "m-1"}
                )
            ]
        )

    await tool_authorization_middleware().awrap_model_call(request, handler)
    assert usage.by_model == {"m-1": TokenCounts(150, 120, 30, 100, 12)}


class _UsageAgent:
    async def ainvoke(
        self, inputs: dict[str, Any], *, config: dict[str, Any], context: Any = None
    ) -> dict[str, Any]:
        context.usage.record(FULL, "model-a")
        context.usage.record({"total_tokens": 8}, "model-b")
        return {
            "messages": [],
            "structured_response": AgentAnswer(answer="a", used_tools=[], confidence=1.0),
        }


@pytest.mark.anyio
async def test_run_logs_model_token_usage_with_split_and_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main_graph, "build_agent", lambda settings: _UsageAgent())
    service = AgentService(Settings(env="test"))

    with structlog.testing.capture_logs() as logs:
        await service.invoke(AgentRequest(message="secret prompt text"))

    [event] = [e for e in logs if e["event"] == "model_token_usage"]
    assert event["provider_tokens"] == 158
    assert (event["input_tokens"], event["output_tokens"]) == (120, 30)
    assert (event["cache_read_tokens"], event["reasoning_tokens"]) == (100, 12)
    assert event["models"] == {
        "model-a": {
            "total_tokens": 150,
            "input_tokens": 120,
            "output_tokens": 30,
            "cache_read_tokens": 100,
            "reasoning_tokens": 12,
        },
        "model-b": {
            "total_tokens": 8,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "reasoning_tokens": 0,
        },
    }
    assert "secret prompt text" not in str(event)


@pytest.mark.anyio
async def test_agent_server_run_logs_model_token_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    """Agent Server runs carry no `AuthorizationContext`, so the graph logs their usage."""
    monkeypatch.setattr(main_graph, "build_agent", lambda settings: _UsageAgent())
    graph = main_graph.build_graph(Settings(env="test"))
    configurable = {"run_id": "run-1", "langgraph_auth_user_id": "a" * 64}

    with structlog.testing.capture_logs() as logs:
        await graph.ainvoke(
            {"messages": [HumanMessage(content="secret prompt text")]},
            config={"configurable": configurable},
        )

    [event] = [e for e in logs if e["event"] == "model_token_usage"]
    assert event["provider_tokens"] == 158
    assert event["run_id"] == "run-1"
    assert event["owner_key_prefix"] == "a" * 12
    assert set(event["models"]) == {"model-a", "model-b"}
    assert "secret prompt text" not in str(event)
