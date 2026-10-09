from __future__ import annotations

import asyncio
import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta
from typing import Any

import pytest
import structlog
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

from neuron_agent.api import main as api_main
from neuron_agent.api.main import app
from neuron_agent.config.settings import Settings
from neuron_agent.errors.base import ExportTooLargeError, ThreadBusyError, ThreadNotFoundError
from neuron_agent.persistence import cli
from neuron_agent.persistence.checkpointer import build_persistence
from neuron_agent.persistence.retention import prune_threads
from neuron_agent.schemas.agent import AgentRequest
from neuron_agent.security.rate_limiter import InMemoryTokenBucketRateLimiter
from neuron_agent.services.agent_service import AgentService

pytestmark = pytest.mark.anyio


def _service(checkpointer: str = "memory") -> AgentService:
    return AgentService(Settings(env="test", checkpointer=checkpointer))


async def _thread(service: AgentService, *messages: str, user_id: str | None = None) -> str:
    thread_id = (await service.invoke(AgentRequest(message=messages[0], user_id=user_id))).thread_id
    for message in messages[1:]:
        await service.invoke(AgentRequest(message=message, thread_id=thread_id, user_id=user_id))
    return thread_id


async def _checkpoint_count(service: AgentService, thread_id: str) -> int:
    checkpointer = service._persistence.checkpointer
    assert checkpointer is not None
    config = {"configurable": {"thread_id": thread_id}}
    return len([c async for c in checkpointer.alist(config)])


# --- history ----------------------------------------------------------------------


@pytest.mark.usefixtures("echo_agent")
async def test_history_returns_turns_in_order_with_pagination() -> None:
    service = _service()
    thread_id = await _thread(service, "one", "two", "three", user_id="alice")

    page = await service.get_history(thread_id, "alice", limit=2, offset=1)
    assert page.total == 6
    assert (page.limit, page.offset) == (2, 1)
    assert [(m.role, m.content) for m in page.messages] == [
        ("assistant", "one"),
        ("user", "two"),
    ]
    everything = await service.get_history(thread_id, "alice", limit=100, offset=0)
    assert [m.role for m in everything.messages] == ["user", "assistant"] * 3


@pytest.mark.usefixtures("echo_agent")
async def test_history_hides_system_and_tool_messages() -> None:
    service = _service()
    thread_id = await _thread(service, "hi")
    tool_call = {"name": "calculator", "args": {"expression": "1+1"}, "id": "c1"}
    await service.graph.aupdate_state(
        {"configurable": {"thread_id": thread_id}},
        {
            "messages": [
                SystemMessage(content="internal prompt"),
                AIMessage(content="", tool_calls=[tool_call]),
                ToolMessage(content="raw tool output", tool_call_id="c1"),
            ]
        },
    )
    page = await service.get_history(thread_id, None, limit=100, offset=0)
    assert [m.content for m in page.messages] == ["hi", "hi"]


@pytest.mark.usefixtures("echo_agent")
async def test_history_is_not_readable_by_others() -> None:
    service = _service()
    owned = await _thread(service, "secret", user_id="alice")
    for thread_id, user_id in [(owned, "mallory"), (owned, None), (str(uuid.uuid4()), "alice")]:
        with pytest.raises(ThreadNotFoundError):
            await service.get_history(thread_id, user_id, limit=10, offset=0)


@pytest.mark.usefixtures("echo_agent")
async def test_bola_denial_is_audited_once_without_identity_or_network_data() -> None:
    service = _service()
    thread_id = await _thread(service, "private", user_id="victim@example.test")

    with structlog.testing.capture_logs() as logs:
        with pytest.raises(ThreadNotFoundError):
            await service.get_history(thread_id, "attacker@example.test", limit=10, offset=0)

    rendered = json.dumps(logs)
    assert "victim@example.test" not in rendered
    assert "attacker@example.test" not in rendered
    assert not re.search(r"\bsub\b", rendered)
    assert not re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", rendered)
    assert not re.search(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", rendered)
    assert not re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", rendered)
    denials = [entry for entry in logs if entry.get("event") == "authorization_denied"]
    assert len(denials) == 1
    assert denials[0]["reason"] == "thread_not_found"


async def test_history_without_persistence_is_not_found() -> None:
    with pytest.raises(ThreadNotFoundError):
        await _service("none").get_history(str(uuid.uuid4()), None, limit=10, offset=0)


# --- delete -----------------------------------------------------------------------


@pytest.mark.usefixtures("echo_agent")
async def test_delete_removes_every_checkpoint() -> None:
    service = _service()
    thread_id = await _thread(service, "one", "two", user_id="alice")
    assert await _checkpoint_count(service, thread_id) > 0

    await service.delete_thread(thread_id, "alice")

    assert await _checkpoint_count(service, thread_id) == 0
    with pytest.raises(ThreadNotFoundError):
        await service.get_history(thread_id, "alice", limit=10, offset=0)
    with pytest.raises(ThreadNotFoundError):
        await service.invoke(AgentRequest(message="x", thread_id=thread_id, user_id="alice"))


@pytest.mark.usefixtures("echo_agent")
async def test_delete_by_non_owner_is_not_found_and_keeps_thread() -> None:
    service = _service()
    thread_id = await _thread(service, "keep", user_id="alice")
    with pytest.raises(ThreadNotFoundError):
        await service.delete_thread(thread_id, "mallory")
    assert (await service.get_history(thread_id, "alice", limit=10, offset=0)).total == 2


@pytest.mark.usefixtures("echo_agent")
async def test_delete_is_rejected_while_a_run_is_in_flight() -> None:
    service = _service()
    thread_id = await _thread(service, "hi")
    service._active_threads.add(thread_id)
    with pytest.raises(ThreadBusyError):
        await service.delete_thread(thread_id, None)
    assert await _checkpoint_count(service, thread_id) > 0


@pytest.mark.usefixtures("echo_agent")
async def test_list_user_threads_is_owner_scoped_and_paginated() -> None:
    service = _service()
    alice_old = await _thread(service, "old", user_id="alice")
    await asyncio.sleep(0.01)
    alice_new = await _thread(service, "new", user_id="alice")
    bob_thread = await _thread(service, "private", user_id="bob")

    page = await service.list_user_threads("alice", limit=1, offset=0)
    next_page = await service.list_user_threads("alice", limit=1, offset=1)

    assert page.total == 2
    assert [item.thread_id for item in page.threads] == [alice_new]
    assert page.threads[0].message_count == 2
    assert [item.thread_id for item in next_page.threads] == [alice_old]
    assert bob_thread not in {item.thread_id for item in [*page.threads, *next_page.threads]}
    checkpointer = service._persistence.checkpointer
    assert checkpointer is not None
    owner = hashlib.sha256(b"alice").hexdigest()
    indexed = [
        item
        async for item in checkpointer.alist(None, filter={"owner": owner})
        if item.config["configurable"].get("checkpoint_ns", "") == ""
    ]
    assert indexed
    assert all(item.metadata["owner"] == owner for item in indexed)


@pytest.mark.usefixtures("echo_agent")
async def test_user_export_contains_only_public_messages_and_paginates() -> None:
    service = _service()
    alice_thread = await _thread(service, "alice prompt", user_id="alice")
    await _thread(service, "bob private prompt", user_id="bob")

    first_page = await service.export_user_data(
        "alice", limit=10, offset=0, message_limit=1, message_offset=0
    )
    second_page = await service.export_user_data(
        "alice", limit=10, offset=0, message_limit=1, message_offset=1
    )

    assert first_page.total_threads == 1
    assert first_page.threads[0].thread_id == alice_thread
    assert first_page.threads[0].message_total == 2
    assert first_page.threads[0].messages[0].content == "alice prompt"
    assert first_page.has_more_messages is True
    assert second_page.threads[0].messages[0].content == "alice prompt"
    contents = [message.content for message in second_page.threads[0].messages]
    assert "bob private prompt" not in contents
    assert not any("system" in content or "tool" in content for content in contents)


@pytest.mark.usefixtures("echo_agent")
async def test_erase_all_is_owner_scoped_busy_aware_and_idempotent() -> None:
    service = _service()
    alice_busy = await _thread(service, "busy", user_id="alice")
    alice_delete = await _thread(service, "delete", user_id="alice")
    bob_thread = await _thread(service, "keep", user_id="bob")
    service._active_threads.add(alice_busy)
    service._active_thread_owners[alice_busy] = hashlib.sha256(b"alice").hexdigest()

    first = await service.erase_user_data("alice")
    second = await service.erase_user_data("alice")

    assert first.erased_count == 1
    assert first.skipped_busy_count == 1
    assert second.erased_count == 0
    assert second.skipped_busy_count == 1
    with pytest.raises(ThreadNotFoundError):
        await service.get_history(alice_delete, "alice", limit=10, offset=0)
    assert (await service.get_history(bob_thread, "bob", limit=10, offset=0)).total == 2


@pytest.mark.usefixtures("echo_agent")
async def test_export_page_honors_configured_size_cap() -> None:
    service = _service()
    service._settings.user_data_export_max_bytes = 65_536
    for index in range(4):
        await _thread(service, f"{index}:" + "x" * 10_000, user_id="alice")

    with pytest.raises(ExportTooLargeError):
        await service.export_user_data(
            "alice", limit=10, offset=0, message_limit=100, message_offset=0
        )


# --- retention --------------------------------------------------------------------


async def _last_activity(service: AgentService, thread_id: str) -> datetime:
    checkpointer = service._persistence.checkpointer
    assert checkpointer is not None
    latest = await checkpointer.aget_tuple({"configurable": {"thread_id": thread_id}})
    assert latest is not None
    return datetime.fromisoformat(latest.checkpoint["ts"])


@pytest.mark.usefixtures("echo_agent")
async def test_prune_deletes_only_stale_threads_and_is_idempotent() -> None:
    service = _service()
    old = await _thread(service, "old")
    await asyncio.sleep(0.01)
    recent = await _thread(service, "recent")
    old_ts, recent_ts = await _last_activity(service, old), await _last_activity(service, recent)
    cutoff = old_ts + (recent_ts - old_ts) / 2

    with structlog.testing.capture_logs() as logs:
        pruned = await prune_threads(service._persistence, older_than=timedelta(0), now=cutoff)
        assert await prune_threads(service._persistence, older_than=timedelta(0), now=cutoff) == 0
    assert pruned == 1
    prune_events = [
        entry
        for entry in logs
        if entry.get("audit") is True and entry.get("event") == "threads_pruned"
    ]
    assert len(prune_events) == 2
    assert [entry["count"] for entry in prune_events] == [1, 0]
    assert await _checkpoint_count(service, old) == 0
    assert await _checkpoint_count(service, recent) > 0


@pytest.mark.usefixtures("echo_agent")
async def test_thread_lifecycle_emits_each_audit_event_once() -> None:
    service = _service()
    with structlog.testing.capture_logs() as logs:
        thread_id = await _thread(service, "hello", user_id="alice")
        await service.get_history(thread_id, "alice", limit=10, offset=0)
        await service.delete_thread(thread_id, "alice")

    events = [entry["event"] for entry in logs if entry.get("audit") is True]
    assert events.count("thread_created") == 1
    assert events.count("thread_read") == 1
    assert events.count("thread_deleted") == 1


async def test_prune_without_persistence_is_a_no_op() -> None:
    persistence = build_persistence(Settings(env="test", checkpointer="none"))
    assert await prune_threads(persistence, older_than=timedelta(days=1)) == 0


def test_prune_cli_rejects_non_positive_retention() -> None:
    with pytest.raises(SystemExit):
        cli.main(["prune", "--older-than-days", "0"])


# --- HTTP -------------------------------------------------------------------------


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, echo_agent: Any) -> TestClient:
    monkeypatch.setattr(api_main, "service", _service())
    return TestClient(app)


def test_get_messages_endpoint(client: TestClient) -> None:
    thread_id = client.post("/v1/agent/invoke", json={"message": "hi", "user_id": "alice"}).json()[
        "thread_id"
    ]
    response = client.get(
        f"/v1/threads/{thread_id}/messages", params={"limit": 1}, headers={"X-User-Id": "alice"}
    )
    assert response.status_code == 200
    assert response.json() == {
        "thread_id": thread_id,
        "messages": [{"role": "user", "content": "hi"}],
        "total": 2,
        "limit": 1,
        "offset": 0,
    }


def test_thread_endpoints_do_not_reveal_existence(client: TestClient) -> None:
    thread_id = client.post("/v1/agent/invoke", json={"message": "hi", "user_id": "alice"}).json()[
        "thread_id"
    ]
    unknown = str(uuid.uuid4())
    responses = [
        client.get(f"/v1/threads/{thread_id}/messages", headers={"X-User-Id": "bob"}),
        client.get(f"/v1/threads/{unknown}/messages", headers={"X-User-Id": "bob"}),
        client.delete(f"/v1/threads/{thread_id}", headers={"X-User-Id": "bob"}),
        client.delete(f"/v1/threads/{unknown}", headers={"X-User-Id": "bob"}),
    ]
    assert {(r.status_code, r.text) for r in responses} == {(404, '{"detail":"thread_not_found"}')}


def test_delete_endpoint_then_thread_is_gone(client: TestClient) -> None:
    thread_id = client.post("/v1/agent/invoke", json={"message": "hi"}).json()["thread_id"]
    assert client.delete(f"/v1/threads/{thread_id}").status_code == 204
    assert client.get(f"/v1/threads/{thread_id}/messages").status_code == 404


def test_user_data_rights_endpoints_are_scoped_paginated_and_idempotent(
    client: TestClient,
) -> None:
    alice_headers = {"X-User-Id": "alice"}
    alice_thread_ids = [
        client.post(
            "/v1/agent/invoke",
            json={"message": f"alice-{i}", "user_id": "alice"},
            headers=alice_headers,
        ).json()["thread_id"]
        for i in range(2)
    ]
    bob_thread_id = client.post(
        "/v1/agent/invoke", json={"message": "bob-secret", "user_id": "bob"}
    ).json()["thread_id"]

    first = client.get("/v1/me/threads", params={"limit": 1}, headers=alice_headers)
    second = client.get("/v1/me/threads", params={"limit": 1, "offset": 1}, headers=alice_headers)
    listed_ids = {
        first.json()["threads"][0]["thread_id"],
        second.json()["threads"][0]["thread_id"],
    }
    assert first.json()["total"] == 2
    assert listed_ids == set(alice_thread_ids)
    assert bob_thread_id not in listed_ids
    assert "messages" not in first.json()["threads"][0]

    exported = client.get(
        "/v1/me/export",
        params={"limit": 1, "message_limit": 1},
        headers=alice_headers,
    )
    assert exported.status_code == 200
    assert exported.json()["total_threads"] == 2
    assert exported.json()["threads"][0]["thread_id"] in set(alice_thread_ids)
    assert exported.json()["threads"][0]["messages"][0]["content"].startswith("alice-")
    assert "bob-secret" not in exported.text

    erased = client.delete("/v1/me/threads", headers=alice_headers)
    assert erased.status_code == 200
    assert erased.json() == {"erased_count": 2, "skipped_busy_count": 0}
    repeated = client.delete("/v1/me/threads", headers=alice_headers)
    assert repeated.json() == {"erased_count": 0, "skipped_busy_count": 0}
    assert (
        client.get(
            f"/v1/threads/{bob_thread_id}/messages", headers={"X-User-Id": "bob"}
        ).status_code
        == 200
    )


@pytest.mark.parametrize(
    "path",
    [
        "/v1/threads/not-a-uuid/messages",
        f"/v1/threads/{uuid.uuid4()}/messages?limit=101",
        f"/v1/threads/{uuid.uuid4()}/messages?offset=-1",
    ],
)
def test_thread_endpoints_validate_input(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 422
    assert response.json() == {"detail": "validation_error"}


def test_thread_endpoints_are_rate_limited(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        api_main,
        "rate_limiter",
        InMemoryTokenBucketRateLimiter(capacity=1, requests_per_window=1, window_seconds=60),
    )
    path = f"/v1/threads/{uuid.uuid4()}/messages"
    assert client.get(path).status_code == 404
    assert client.get(path).status_code == 429
