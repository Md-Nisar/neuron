"""LangChain model and agent construction boundaries."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI

from neuron_agent.config.settings import Settings
from neuron_agent.prompts.loader import load_prompt
from neuron_agent.schemas.agent import AgentAnswer


def create_main_agent(settings: Settings, tools: Sequence[BaseTool]) -> Any:
    """Create the configurable LangChain agent harness."""
    model = create_chat_model(settings)
    return create_agent(
        model=model,
        tools=list(tools),
        system_prompt=load_prompt("system/main.md"),
        response_format=AgentAnswer,
        name="neuron_main_agent",
    )


def create_chat_model(settings: Settings) -> ChatOpenAI | FakeListChatModel:
    """Create the chat model with provider-specific runtime limits."""
    if settings.env in {"development", "test"} and settings.openai_api_key is None:
        return FakeListChatModel(responses=["Local test response."])

    provider, model_name = _split_model_identifier(settings.default_model)
    if provider != "openai":
        raise ValueError(f"unsupported model provider: {provider}")

    api_key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else None
    return ChatOpenAI(
        model=model_name,
        api_key=api_key,
        timeout=settings.request_timeout_seconds,
        max_tokens=settings.max_output_tokens,
    )


def agent_invocation_config(settings: Settings) -> dict[str, int]:
    """Return runtime controls for the agent loop and tool execution budget."""
    return {
        "recursion_limit": settings.max_agent_iterations,
        "timeout": settings.tool_timeout_seconds,
    }


def _split_model_identifier(identifier: str) -> tuple[str, str]:
    provider, separator, model_name = identifier.partition(":")
    if not separator or not provider or not model_name:
        raise ValueError("model identifier must use provider:model format")
    return provider, model_name
