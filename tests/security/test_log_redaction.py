"""Regression coverage for issue #9's log-safety acceptance criteria:
API keys/secrets are never logged, and user prompts are not logged indiscriminately.
"""

from __future__ import annotations

import pytest
import structlog
from langchain_core.messages import AIMessage
from pydantic import SecretStr

from neuron_agent.config.settings import Settings
from neuron_agent.models.factory import create_chat_model
from neuron_agent.schemas.agent import AgentAnswer, AgentRequest
from neuron_agent.services.agent_service import AgentService

pytestmark = pytest.mark.anyio

_PROMPT_SENTINEL = "sentinel-user-prompt-should-never-be-logged"
_SECRET_SENTINEL = "sk-test-secret-should-never-leak"  # noqa: S105 -- leakage-detection fixture, not a real secret


class _FakeAgent:
    """Stands in for the real LangChain agent so `call_agent`'s logging runs for
    real without hitting `FakeListChatModel`'s unsupported `bind_tools`."""

    async def ainvoke(
        self, _: dict[str, object], *, config: dict[str, object]
    ) -> dict[str, object]:
        return {
            "messages": [AIMessage(content="ok")],
            "structured_response": AgentAnswer(answer="ok", used_tools=[], confidence=1.0),
        }


def _flatten_log_text(captured: list[dict[str, object]]) -> str:
    return " ".join(str(value) for entry in captured for value in entry.values())


async def test_agent_service_invoke_never_logs_the_user_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("neuron_agent.graphs.main_graph.build_agent", lambda settings: _FakeAgent())
    settings = Settings(env="test", openai_api_key=None)
    service = AgentService(settings)

    with structlog.testing.capture_logs(
        processors=(structlog.contextvars.merge_contextvars,)
    ) as captured:
        await service.invoke(AgentRequest(message=_PROMPT_SENTINEL))

    assert _PROMPT_SENTINEL not in _flatten_log_text(captured)


def test_create_chat_model_never_logs_the_api_key() -> None:
    settings = Settings(
        env="production",
        default_model="openai:gpt-5.4-mini",
        openai_api_key=SecretStr(_SECRET_SENTINEL),
    )

    with structlog.testing.capture_logs(
        processors=(structlog.contextvars.merge_contextvars,)
    ) as captured:
        model = create_chat_model(settings)

    assert model.openai_api_key is not None
    assert _SECRET_SENTINEL not in _flatten_log_text(captured)
