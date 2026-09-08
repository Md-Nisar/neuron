"""LangChain model and agent construction boundaries."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

import openai
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, ToolCallRequest, wrap_tool_call
from langchain.agents.structured_output import (
    StructuredOutputError as LangChainStructuredOutputError,
)
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI
from langgraph.types import Command

from neuron_agent.config.settings import Settings
from neuron_agent.errors.base import (
    AgentExecutionError,
    AppError,
    ConfigurationError,
    ProviderError,
    ProviderTimeoutError,
    ToolExecutionError,
)
from neuron_agent.errors.base import RateLimitError as AppRateLimitError
from neuron_agent.errors.base import StructuredOutputError as AppStructuredOutputError
from neuron_agent.prompts.loader import load_prompt
from neuron_agent.schemas.agent import AgentAnswer


def tool_timeout_middleware(timeout_seconds: float) -> AgentMiddleware:
    """Bound every tool call to `timeout_seconds`, raising ToolExecutionError past it."""

    @wrap_tool_call
    async def enforce_tool_timeout(
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        try:
            return await asyncio.wait_for(handler(request), timeout=timeout_seconds)
        except TimeoutError as exc:
            tool_name = request.tool_call.get("name", "unknown")
            raise ToolExecutionError(
                f"tool '{tool_name}' exceeded {timeout_seconds}s timeout"
            ) from exc

    return enforce_tool_timeout


def create_main_agent(settings: Settings, tools: Sequence[BaseTool]) -> Any:
    """Create the configurable LangChain agent harness."""
    model = create_chat_model(settings)
    return create_agent(
        model=model,
        tools=list(tools),
        system_prompt=load_prompt("system/main.md"),
        response_format=AgentAnswer,
        middleware=[tool_timeout_middleware(settings.tool_timeout_seconds)],
        name="neuron_main_agent",
    )


def create_chat_model(settings: Settings) -> ChatOpenAI | FakeListChatModel:
    """Create the chat model with provider-specific runtime limits."""
    if settings.env in {"development", "test"} and settings.openai_api_key is None:
        return FakeListChatModel(responses=["Local test response."])

    provider, model_name = _split_model_identifier(settings.default_model)
    if provider != "openai":
        raise ConfigurationError(f"unsupported model provider: {provider}")

    api_key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else None
    return ChatOpenAI(
        model=model_name,
        api_key=api_key,
        timeout=settings.request_timeout_seconds,
        max_tokens=settings.max_output_tokens,
    )


def agent_invocation_config(settings: Settings) -> dict[str, int]:
    """Return the runtime recursion budget for the agent loop."""
    return {"recursion_limit": settings.max_agent_iterations}


def classify_agent_error(exc: Exception) -> AppError:
    """Map a raw exception from the agent harness to the application error taxonomy."""
    if isinstance(exc, AppError):
        return exc
    if isinstance(exc, openai.RateLimitError):
        return AppRateLimitError("model provider rate limit exceeded")
    if isinstance(exc, openai.APITimeoutError):
        return ProviderTimeoutError("model provider timed out")
    if isinstance(exc, openai.AuthenticationError):
        return ConfigurationError("model provider authentication failed")
    if isinstance(exc, openai.OpenAIError):
        return ProviderError("model provider request failed")
    if isinstance(exc, LangChainStructuredOutputError):
        return AppStructuredOutputError("agent produced invalid structured output")
    return AgentExecutionError("agent execution failed")


def _split_model_identifier(identifier: str) -> tuple[str, str]:
    provider, separator, model_name = identifier.partition(":")
    if not separator or not provider or not model_name:
        raise ConfigurationError("model identifier must use provider:model format")
    return provider, model_name
