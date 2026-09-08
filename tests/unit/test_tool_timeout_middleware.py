from __future__ import annotations

import asyncio

import pytest
from langchain_core.messages import ToolMessage

from neuron_agent.errors.base import ToolExecutionError
from neuron_agent.models.factory import tool_timeout_middleware

pytestmark = pytest.mark.anyio


class _FakeRequest:
    def __init__(self, name: str) -> None:
        self.tool_call = {"name": name, "args": {}, "id": "call-1"}


async def test_tool_timeout_middleware_allows_fast_tool() -> None:
    middleware = tool_timeout_middleware(timeout_seconds=0.2)

    async def fast_handler(request: object) -> ToolMessage:
        return ToolMessage(content="ok", tool_call_id="call-1")

    result = await middleware.awrap_tool_call(_FakeRequest("fast_tool"), fast_handler)
    assert result.content == "ok"


async def test_tool_timeout_middleware_raises_on_slow_tool() -> None:
    middleware = tool_timeout_middleware(timeout_seconds=0.05)

    async def slow_handler(request: object) -> ToolMessage:
        await asyncio.sleep(1)
        return ToolMessage(content="too late", tool_call_id="call-1")

    with pytest.raises(ToolExecutionError):
        await middleware.awrap_tool_call(_FakeRequest("slow_tool"), slow_handler)
