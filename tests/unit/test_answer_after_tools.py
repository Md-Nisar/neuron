"""An answer given alongside other tool calls waits for their results (RAG-11.01)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
import structlog.testing
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from neuron_agent.api import main as api_main
from neuron_agent.api.main import app
from neuron_agent.config.settings import Settings
from neuron_agent.services.agent_service import AgentService


def _answer(text: str, call_id: str) -> dict[str, Any]:
    args = {"answer": text, "used_tools": ["utc_now"], "confidence": 0.9}
    return {"name": "AgentAnswer", "args": args, "id": call_id}


def test_the_model_answers_again_after_the_tools_it_called_with_its_answer(
    stream_replies: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    early = AIMessage(
        content="",
        tool_calls=[{"name": "utc_now", "args": {}, "id": "t1"}, _answer("I need the time.", "a1")],
    )
    model = stream_replies(early, AIMessage(content="", tool_calls=[_answer("It is noon.", "a2")]))
    monkeypatch.setattr(api_main, "service", AgentService(Settings(env="test")))

    with structlog.testing.capture_logs() as logs:
        response = TestClient(app).post("/v1/agent/invoke", json={"message": "time?"})

    assert response.status_code == 200
    assert response.json()["answer"] == "It is noon."
    assert list(model.messages) == []  # both replies used: the model was called again
    assert any(log["event"] == "early_answer_dropped" for log in logs)
