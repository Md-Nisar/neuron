"""An answer after `find_tables` found tables that were never queried is asked again (RAG-11.01)."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from types import SimpleNamespace
from typing import Any

import pytest
import structlog.testing
from langchain.agents.middleware import ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from neuron_agent.config.settings import Settings
from neuron_agent.models.factory import agent_middleware, query_after_find_middleware
from neuron_agent.security.authorization import AuthorizationContext, TokenUsageAccumulator
from neuron_agent.tools.registry import builtin_registry

pytestmark = pytest.mark.anyio

_USAGE = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
_TOOLS = [{"name": "find_tables"}, {"name": "query_table"}]


@dataclass
class _Request:
    messages: list[Any]
    tools: list[Any] = field(default_factory=lambda: list(_TOOLS))
    runtime: Any = field(default_factory=lambda: SimpleNamespace(context=None))
    tool_choice: Any = None
    response_format: Any = "AgentAnswer"

    def override(self, **changes: Any) -> _Request:
        return replace(self, **changes)


def _found(artifact: dict[str, Any] | None = None) -> ToolMessage:
    artifact = {"t1a2b3c4": {"doc_id": "d", "position": 0}} if artifact is None else artifact
    return ToolMessage("tables", tool_call_id="f", name="find_tables", artifact=artifact)


def _queried(status: str = "success") -> ToolMessage:
    return ToolMessage("rows", tool_call_id="q", name="query_table", artifact={}, status=status)


def _answer(text: str) -> ModelResponse:
    reply = AIMessage(content=text, usage_metadata=_USAGE)  # type: ignore[arg-type]
    return ModelResponse(result=[reply], structured_response={"answer": text})


async def _run(request: _Request, *replies: ModelResponse) -> tuple[Any, list[_Request]]:
    seen: list[_Request] = []
    queue = list(replies)

    async def handler(r: _Request) -> ModelResponse:
        seen.append(r)
        return queue.pop(0)

    return await query_after_find_middleware().awrap_model_call(request, handler), seen


_CALLS = AIMessage("", tool_calls=[{"name": "find_tables", "args": {}, "id": "f"}])
_LATER = AIMessage("", tool_calls=[{"name": "query_table", "args": {}, "id": "q"}])


@pytest.mark.parametrize(
    "earlier",
    [
        [],  # never queried
        [_queried("error")],  # a guessed handle, queried in the same reply as find_tables
        [_queried("success")],  # its result arrived after the tables, still the same reply
    ],
)
async def test_an_answer_without_a_query_is_set_aside_charged_and_a_query_required(
    earlier: list[Any],
) -> None:
    usage = TokenUsageAccumulator()
    context = AuthorizationContext(frozenset(), usage=usage)
    request = _Request(
        [HumanMessage("total?"), _CALLS, _found(), *earlier],
        runtime=SimpleNamespace(context=context),
    )
    query = AIMessage("", tool_calls=[{"name": "query_table", "args": {}, "id": "q"}])

    with structlog.testing.capture_logs() as logs:
        response, seen = await _run(request, _answer("About 300."), ModelResponse(result=[query]))

    assert response.result == [query]
    assert len(seen) == 2
    assert seen[1].tools == [{"name": "query_table"}]
    assert (seen[1].tool_choice, seen[1].response_format) == ("any", None)
    assert "query_table" in seen[1].messages[-1].content
    assert request.messages == seen[0].messages  # the note is not kept in the thread
    assert usage.total_tokens == _USAGE["total_tokens"]
    assert any(log["event"] == "table_query_requested" for log in logs)


@pytest.mark.parametrize(
    "request_",
    [
        _Request([HumanMessage("total?"), _CALLS, _found(), _LATER, _queried()]),  # queried
        _Request([HumanMessage("total?"), _CALLS, _LATER, _queried("error")]),  # nothing found
        _Request([HumanMessage("total?"), _CALLS, _found({})]),  # no table found
        _Request([_found(), HumanMessage("total?")]),  # found in an earlier turn
        _Request([HumanMessage("total?"), _found()], tools=[]),  # the run's last call
        _Request([HumanMessage("total?"), _found()], tools=[{"name": "find_tables"}]),
    ],
)
async def test_the_answer_stands_otherwise(request_: _Request) -> None:
    response, seen = await _run(request_, _answer("2,907."))

    assert response.structured_response == {"answer": "2,907."}
    assert len(seen) == 1


async def test_a_provider_that_ignores_the_required_call_keeps_the_first_answer() -> None:
    usage = TokenUsageAccumulator()
    context = AuthorizationContext(frozenset(), usage=usage)
    request = _Request(
        [HumanMessage("total?"), _CALLS, _found()], runtime=SimpleNamespace(context=context)
    )
    text = AIMessage("I will query it.", usage_metadata=_USAGE)  # type: ignore[arg-type]

    with structlog.testing.capture_logs() as logs:
        response, seen = await _run(request, _answer("About 300."), ModelResponse(result=[text]))

    assert response.structured_response == {"answer": "About 300."}
    assert len(seen) == 2
    assert usage.total_tokens == _USAGE["total_tokens"]  # the ignored call is charged
    assert any(log["event"] == "table_query_skipped" for log in logs)


def test_it_sits_inside_tool_authorization() -> None:
    kinds = [type(m).__name__ for m in agent_middleware(Settings(env="test"), builtin_registry())]
    assert kinds.index("_ToolAuthorizationMiddleware") < kinds.index("_QueryAfterFindMiddleware")


async def test_response_that_already_calls_query_table_is_not_discarded() -> None:
    request = _Request([HumanMessage("total?"), _CALLS, _found()])
    combined = ModelResponse(
        result=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "query_table",
                        "args": {"table": "t0", "sql": "SELECT 1"},
                        "id": "call_q1",
                        "type": "tool_call",
                    }
                ],
            )
        ],
        structured_response={"answer": "partial"},
    )
    response, seen = await _run(request, combined)
    assert response is combined
    assert len(seen) == 1
