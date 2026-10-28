"""The approval API end to end with real tokens (#242, ADR 0009 decision 6)."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from typing import Any

import pytest
import structlog.testing
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from tests.conftest import JwtApi, StreamingFakeModel, bearer

from neuron_agent.api import main as api_main
from neuron_agent.models import factory
from neuron_agent.tools.registry import ToolRegistry, ToolSpec, builtin_registry

_ran: list[str] = []
_USAGE = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
_OWNER = "agent:invoke agent:approve threads:read threads:delete tools:note_taker"
_NOT_FOUND = {"detail": "approval_not_found"}


@tool
def note_taker(text: str) -> str:
    """Save a note. This changes data outside the conversation."""
    _ran.append(text)
    return "saved"


@pytest.fixture(autouse=True)
def _reset() -> None:
    _ran.clear()


def _call(text: str = "buy milk") -> AIMessage:
    call = {"name": "note_taker", "args": {"text": text}, "id": f"call-{uuid.uuid4().hex[:6]}"}
    return AIMessage(content="", tool_calls=[call], usage_metadata=_USAGE)  # type: ignore[arg-type]


def _final(text: str) -> AIMessage:
    return AIMessage(content=text, usage_metadata=_USAGE)  # type: ignore[arg-type]


@pytest.fixture
def api(
    jwt_api_factory: Callable[..., JwtApi], monkeypatch: pytest.MonkeyPatch
) -> Callable[..., JwtApi]:
    """The API with a mutating `note_taker` and a model that replays the given messages."""

    def build(*replies: AIMessage) -> JwtApi:
        monkeypatch.setattr(
            factory,
            "create_chat_model",
            lambda _: StreamingFakeModel(messages=iter(replies)),
        )
        built = jwt_api_factory()
        built.service.use_registry(
            ToolRegistry(
                [*builtin_registry(), ToolSpec(note_taker, "tools:note_taker", "mutating")]
            )
        )
        asyncio.run(built.service.startup())
        return built

    return build


def _ask(api: JwtApi, token: str, thread_id: str | None = None) -> Any:
    body: dict[str, Any] = {"message": "remember to buy milk"}
    if thread_id:
        body["thread_id"] = thread_id
    return api.client.post("/v1/agent/invoke", json=body, headers=bearer(token))


def _decide(api: JwtApi, token: str, thread_id: str, approval_id: str, decision: str) -> Any:
    return api.client.post(
        f"/v1/threads/{thread_id}/approvals/{approval_id}",
        json={"decision": decision},
        headers=bearer(token),
    )


def test_a_gated_call_returns_the_pending_action_in_full(
    api: Callable[..., JwtApi], make_token: Callable[..., str]
) -> None:
    app = api(_call("buy milk"), _final("saved"))
    token = make_token("alice", scopes=_OWNER)

    with structlog.testing.capture_logs() as logs:
        response = _ask(app, token)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "approval_required"
    assert body["approval"]["actions"] == [{"name": "note_taker", "args": {"text": "buy milk"}}]
    assert body["approval"]["allowed_decisions"] == ["approve", "reject"]
    assert body["approval"]["approval_id"] and body["thread_id"]
    assert "answer" not in body
    assert _ran == []
    [event] = [log for log in logs if log["event"] == "approval_requested" and log.get("audit")]
    assert (event["resource_type"], event["resource_id"], event["count"]) == (
        "approval",
        body["approval"]["approval_id"],
        1,
    )


def test_approve_runs_the_tool_once_and_the_approval_cannot_be_used_again(
    api: Callable[..., JwtApi], make_token: Callable[..., str]
) -> None:
    app = api(_call(), _final("I saved your note."))
    token = make_token("alice", scopes=_OWNER)
    paused = _ask(app, token).json()
    thread, approval = paused["thread_id"], paused["approval"]["approval_id"]

    with structlog.testing.capture_logs() as logs:
        done = _decide(app, token, thread, approval, "approve")
        again = _decide(app, token, thread, approval, "approve")

    assert done.status_code == 200, done.text
    assert done.json()["status"] == "completed"
    assert done.json()["answer"] == "I saved your note."
    assert done.json()["used_tools"] == ["note_taker"]
    assert done.json()["request_id"] != paused["request_id"]  # a new run
    assert _ran == ["buy milk"]
    assert (again.status_code, again.json()) == (404, _NOT_FOUND)
    assert _ran == ["buy milk"]
    [decided] = [log for log in logs if log["event"] == "approval_decided"]
    assert (decided["reason"], decided["resource_id"], decided["action"]) == (
        "approve",
        approval,
        "agent:approve",
    )
    history = app.client.get(f"/v1/threads/{thread}/messages", headers=bearer(token)).json()
    assert [(m["role"], m["content"]) for m in history["messages"]] == [
        ("user", "remember to buy milk"),
        ("assistant", "I saved your note."),
    ]
    # Each run was charged for the model call it made, and for that one only.
    usage = [log["provider_tokens"] for log in logs if log["event"] == "model_token_usage"]
    assert usage == [15]


def test_reject_never_runs_the_tool(
    api: Callable[..., JwtApi], make_token: Callable[..., str]
) -> None:
    app = api(_call(), _final("Understood, I did not save it."))
    token = make_token("alice", scopes=_OWNER)
    paused = _ask(app, token).json()

    done = _decide(app, token, paused["thread_id"], paused["approval"]["approval_id"], "reject")

    assert done.status_code == 200, done.text
    assert done.json()["answer"] == "Understood, I did not save it."
    assert done.json()["used_tools"] == []
    assert _ran == []


def test_another_user_cannot_decide_it_and_gets_the_same_404_as_for_an_unknown_id(
    api: Callable[..., JwtApi], make_token: Callable[..., str]
) -> None:
    app = api(_call(), _final("saved"))
    alice = make_token("alice", scopes=_OWNER)
    mallory = make_token("mallory", scopes=_OWNER)
    paused = _ask(app, alice).json()
    thread, approval = paused["thread_id"], paused["approval"]["approval_id"]

    stolen = _decide(app, mallory, thread, approval, "approve")
    unknown = _decide(app, mallory, str(uuid.uuid4()), approval, "approve")
    wrong_id = _decide(app, alice, thread, "0" * 32, "approve")

    assert [r.status_code for r in (stolen, unknown, wrong_id)] == [404, 404, 404]
    assert stolen.json() == unknown.json() == wrong_id.json() == _NOT_FOUND
    assert _ran == []
    # The owner's approval is untouched by the attempts.
    assert _decide(app, alice, thread, approval, "approve").status_code == 200
    assert _ran == ["buy milk"]


def test_the_route_needs_its_own_scope(
    api: Callable[..., JwtApi], make_token: Callable[..., str]
) -> None:
    app = api(_call(), _final("saved"))
    paused = _ask(app, make_token("alice", scopes=_OWNER)).json()
    without = make_token("alice", scopes="agent:invoke threads:read tools:note_taker")

    response = _decide(
        app, without, paused["thread_id"], paused["approval"]["approval_id"], "approve"
    )

    assert response.status_code == 403
    assert _ran == []


def test_a_new_message_on_a_pending_thread_is_refused_until_it_is_decided(
    api: Callable[..., JwtApi], make_token: Callable[..., str]
) -> None:
    app = api(_call(), _final("saved"), _final("second answer"))
    token = make_token("alice", scopes=_OWNER)
    paused = _ask(app, token).json()
    thread, approval = paused["thread_id"], paused["approval"]["approval_id"]

    refused = _ask(app, token, thread)
    assert (refused.status_code, refused.json()) == (409, {"detail": "approval_pending"})

    assert _decide(app, token, thread, approval, "approve").status_code == 200
    assert _ask(app, token, thread).json()["answer"] == "second answer"


def test_a_malformed_request_is_a_validation_error(
    api: Callable[..., JwtApi], make_token: Callable[..., str]
) -> None:
    app = api(_call(), _final("saved"))
    token = make_token("alice", scopes=_OWNER)
    paused = _ask(app, token).json()
    path = f"/v1/threads/{paused['thread_id']}/approvals/{paused['approval']['approval_id']}"

    for body in ({"decision": "edit"}, {"decision": "approve", "args": {"text": "x"}}, {}):
        assert app.client.post(path, json=body, headers=bearer(token)).status_code == 422
    assert _ran == []


def test_the_route_is_documented_with_both_response_shapes() -> None:
    schema = api_main.app.openapi()
    operation = schema["paths"]["/v1/threads/{thread_id}/approvals/{approval_id}"]["post"]
    assert "ApprovalDecisionRequest" in str(operation["requestBody"])
    responses = str(operation["responses"]["200"])
    assert "AgentResponse" in responses and "ApprovalRequiredResponse" in responses
    invoke = str(schema["paths"]["/v1/agent/invoke"]["post"]["responses"]["200"])
    assert "ApprovalRequiredResponse" in invoke


def test_a_pending_thread_is_listed_exported_and_erasable(
    api: Callable[..., JwtApi], make_token: Callable[..., str]
) -> None:
    """The user-rights routes read `messages` only, so a paused thread shows no tool call."""
    app = api(_call("secret-note-text"), _final("saved"))
    token = make_token("alice", scopes=_OWNER)
    paused = _ask(app, token).json()
    thread = paused["thread_id"]

    listing = app.client.get("/v1/me/threads", headers=bearer(token))
    export = app.client.get("/v1/me/export", headers=bearer(token))

    assert listing.status_code == export.status_code == 200
    assert [t["thread_id"] for t in listing.json()["threads"]] == [thread]
    assert "secret-note-text" not in export.text  # the pending call is not conversation history
    erased = app.client.delete("/v1/me/threads", headers=bearer(token))
    assert erased.json()["erased_count"] == 1
    assert (
        _decide(app, token, thread, paused["approval"]["approval_id"], "approve").status_code == 404
    )
