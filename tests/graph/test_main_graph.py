from __future__ import annotations

import httpx
import openai
import pytest
from langchain.agents.structured_output import StructuredOutputValidationError
from langchain_core.messages import AIMessage, HumanMessage

from neuron_agent.errors.base import (
    AgentExecutionError,
    ConfigurationError,
    ProviderError,
    ProviderTimeoutError,
    RateLimitError,
)
from neuron_agent.errors.base import StructuredOutputError as AppStructuredOutputError
from neuron_agent.graphs.main_graph import call_agent
from neuron_agent.schemas.agent import AgentAnswer
from neuron_agent.state.main import MainGraphState

pytestmark = pytest.mark.anyio

_REQUEST = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")


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


class FailingAgent:
    def __init__(self, error: Exception) -> None:
        self._error = error

    async def ainvoke(
        self, _: dict[str, object], *, config: dict[str, object]
    ) -> dict[str, object]:
        raise self._error


def _state() -> MainGraphState:
    return {
        "messages": [HumanMessage(content="2+2")],
        "request_id": "request-1",
        "thread_id": "thread-1",
    }


async def test_call_agent_uses_structured_response() -> None:
    result = await call_agent(_state(), agent=FakeAgent())
    assert result["answer"].answer == "4"
    assert result["answer"].used_tools == ["calculator"]


async def test_call_agent_wraps_rate_limit_error() -> None:
    response = httpx.Response(status_code=429, request=_REQUEST)
    error = openai.RateLimitError("rate limited", response=response, body=None)
    with pytest.raises(RateLimitError):
        await call_agent(_state(), agent=FailingAgent(error))


async def test_call_agent_wraps_timeout_error() -> None:
    error = openai.APITimeoutError(request=_REQUEST)
    with pytest.raises(ProviderTimeoutError):
        await call_agent(_state(), agent=FailingAgent(error))


async def test_call_agent_wraps_authentication_error() -> None:
    response = httpx.Response(status_code=401, request=_REQUEST)
    error = openai.AuthenticationError("bad key", response=response, body=None)
    with pytest.raises(ConfigurationError):
        await call_agent(_state(), agent=FailingAgent(error))


async def test_call_agent_wraps_generic_provider_error() -> None:
    error = openai.APIConnectionError(request=_REQUEST)
    with pytest.raises(ProviderError):
        await call_agent(_state(), agent=FailingAgent(error))


async def test_call_agent_wraps_structured_output_error() -> None:
    error = StructuredOutputValidationError(
        tool_name="AgentAnswer",
        source=ValueError("bad structured output"),
        ai_message=AIMessage(content="not structured"),
    )
    with pytest.raises(AppStructuredOutputError):
        await call_agent(_state(), agent=FailingAgent(error))


async def test_call_agent_wraps_unexpected_error() -> None:
    with pytest.raises(AgentExecutionError):
        await call_agent(_state(), agent=FailingAgent(RuntimeError("boom")))
