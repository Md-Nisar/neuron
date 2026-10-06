from __future__ import annotations

import os
from typing import Any

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

# Must run before importing neuron_agent: settings and the exported graph build at import.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("APP_DEFAULT_MODEL", "openai:gpt-5.4-mini")

from neuron_agent.api import main as api_main  # noqa: E402
from neuron_agent.graphs import main_graph  # noqa: E402
from neuron_agent.schemas.agent import AgentAnswer  # noqa: E402
from neuron_agent.security.rate_limiter import InMemoryTokenBucketRateLimiter  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_rate_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give each test its own API rate limiter so request counts don't leak across tests."""
    settings = api_main.settings
    monkeypatch.setattr(
        api_main,
        "rate_limiter",
        InMemoryTokenBucketRateLimiter(
            capacity=settings.rate_limit_burst,
            requests_per_window=settings.rate_limit_requests_per_window,
            window_seconds=settings.rate_limit_window_seconds,
        ),
    )


class HistoryEchoAgent:
    """Deterministic agent: answers with every user turn it was given, oldest first.

    It also returns an intermediate tool-call/tool-result pair, the way `create_agent` does,
    so tests can assert that those internal messages are not persisted to the thread.
    """

    def __init__(self) -> None:
        self.calls: list[list[BaseMessage]] = []
        self.fail_next = False

    async def ainvoke(self, inputs: dict[str, Any], *, config: dict[str, Any]) -> dict[str, Any]:
        messages = list(inputs["messages"])
        self.calls.append(messages)
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("agent failed")
        answer = " | ".join(str(m.content) for m in messages if isinstance(m, HumanMessage))
        tool_call = {"name": "calculator", "args": {"expression": "1+1"}, "id": "call-1"}
        return {
            "messages": [
                *messages,
                AIMessage(content="", tool_calls=[tool_call]),
                ToolMessage(content="2", tool_call_id="call-1"),
                AIMessage(content=answer),
            ],
            "structured_response": AgentAnswer(answer=answer, used_tools=[], confidence=1.0),
        }


@pytest.fixture
def echo_agent(monkeypatch: pytest.MonkeyPatch) -> HistoryEchoAgent:
    """Make every graph built during the test use a `HistoryEchoAgent`."""
    agent = HistoryEchoAgent()
    monkeypatch.setattr(main_graph, "build_agent", lambda settings: agent)
    return agent
