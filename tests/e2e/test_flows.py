"""Each user-facing flow, end to end, against a real API process (fake model, JWT auth)."""

from __future__ import annotations

import uuid
from collections.abc import Callable

import httpx
from tests.e2e.conftest import Api, stream_events

Make = Callable[[str], httpx.Client]


def _run(
    client: httpx.Client, message: str, thread_id: str | None = None
) -> list[tuple[str, dict]]:
    body: dict[str, str] = {"message": message}
    if thread_id:
        body["thread_id"] = thread_id
    response = client.post("/v1/agent/stream", json=body)
    assert response.status_code == 200, response.text
    return stream_events(response)


def _thread_id(events: list[tuple[str, dict]]) -> str:
    return str(events[0][1]["thread_id"])


def _ask_to_remember(client: httpx.Client, text: str) -> tuple[str, str]:
    """Run `remember: ...` and return the thread and approval ids it paused on."""
    events = _run(client, f"remember: {text}")
    names = [name for name, _ in events]
    assert names[-2:] == ["approval_required", "done"] and "final" not in names
    approval = dict(events[-2][1])["approval"]
    assert approval["actions"] == [{"name": "remember", "args": {"text": text}}]
    return _thread_id(events), str(approval["approval_id"])


def test_health_is_open_and_everything_else_needs_a_token(api: Api) -> None:
    assert httpx.get(f"{api.base_url}/health/live").status_code == 200
    assert httpx.get(f"{api.base_url}/health/ready").json()["status"] == "ready"
    assert httpx.get(f"{api.base_url}/v1/me/threads").status_code == 401
    assert httpx.post(f"{api.base_url}/v1/agent/stream", json={"message": "hi"}).status_code == 401


def test_chat_streams_an_answer_and_the_conversation_resumes(user: Make) -> None:
    client = user("chat")
    events = _run(client, "What is 2+2?")
    names = [name for name, _ in events]
    assert names[0] == "run_started" and names[-2:] == ["final", "done"] and "token" in names
    final = dict(events[-2][1])
    assert final["status"] == "completed" and final["answer"] and not final["refused"]
    thread_id = _thread_id(events)

    _run(client, "And 3+3?", thread_id)
    history = client.get(f"/v1/threads/{thread_id}/messages").json()
    assert history["total"] == 4
    assert [m["role"] for m in history["messages"]] == ["user", "assistant", "user", "assistant"]
    assert history["messages"][0]["content"] == "What is 2+2?"

    listed = client.get("/v1/me/threads").json()
    assert [t["thread_id"] for t in listed["threads"]] == [thread_id]


def test_a_remembered_note_waits_for_approval_and_is_stored_once_approved(user: Make) -> None:
    client = user("approve")
    thread_id, approval_id = _ask_to_remember(client, "I like tea")
    assert client.get("/v1/me/memories").json()["total"] == 0  # nothing stored before approval

    pending = client.get(f"/v1/threads/{thread_id}/approval").json()  # a reloaded client
    assert pending["approval"]["approval_id"] == approval_id

    response = client.post(
        f"/v1/threads/{thread_id}/approvals/{approval_id}/stream", json={"decision": "approve"}
    )
    names = [name for name, _ in stream_events(response)]
    assert names[-2:] == ["final", "done"]
    memories = client.get("/v1/me/memories").json()
    assert [m["text"] for m in memories["memories"]] == ["I like tea"]

    again = client.post(
        f"/v1/threads/{thread_id}/approvals/{approval_id}", json={"decision": "approve"}
    )
    assert again.status_code == 404  # a decision is final
    assert client.get(f"/v1/threads/{thread_id}/approval").status_code == 404


def test_a_rejected_note_is_not_stored(user: Make) -> None:
    client = user("reject")
    thread_id, approval_id = _ask_to_remember(client, "I dislike coffee")
    response = client.post(
        f"/v1/threads/{thread_id}/approvals/{approval_id}", json={"decision": "reject"}
    )
    assert response.status_code == 200
    assert client.get("/v1/me/memories").json()["total"] == 0


def test_memories_can_be_deleted_one_at_a_time_or_all_at_once(user: Make) -> None:
    client = user("memories")
    for text in ("first note", "second note"):
        thread_id, approval_id = _ask_to_remember(client, text)
        client.post(
            f"/v1/threads/{thread_id}/approvals/{approval_id}", json={"decision": "approve"}
        )
    items = client.get("/v1/me/memories").json()["memories"]
    assert sorted(m["text"] for m in items) == ["first note", "second note"]

    assert client.delete(f"/v1/me/memories/{items[0]['id']}").status_code == 204
    assert client.get("/v1/me/memories").json()["total"] == 1
    assert client.delete("/v1/me/memories").json() == {"erased_count": 1}
    assert client.get("/v1/me/memories").json()["total"] == 0


def test_a_thread_can_be_renamed_rated_and_deleted(user: Make) -> None:
    client = user("thread")
    events = _run(client, "Hello")
    thread_id, run_id = _thread_id(events), str(events[0][1]["run_id"])

    renamed = client.patch(f"/v1/threads/{thread_id}", json={"title": "Tea talk"})
    assert renamed.json() == {"thread_id": thread_id, "title": "Tea talk"}
    assert client.get("/v1/me/threads").json()["threads"][0]["title"] == "Tea talk"

    rated = client.post(f"/v1/threads/{thread_id}/runs/{run_id}/feedback", json={"score": 1})
    assert rated.json() == {"run_id": run_id, "score": 1, "reason": None}
    bad = client.post(f"/v1/threads/{thread_id}/runs/{run_id}/feedback", json={"score": True})
    assert bad.status_code == 422

    assert client.delete(f"/v1/threads/{thread_id}").status_code == 204
    assert client.get(f"/v1/threads/{thread_id}/messages").status_code == 404
    assert client.get("/v1/me/threads").json()["total"] == 0


def test_a_user_can_export_and_then_erase_their_data(user: Make) -> None:
    client = user("rights")
    thread_id, approval_id = _ask_to_remember(client, "export me")
    client.post(f"/v1/threads/{thread_id}/approvals/{approval_id}", json={"decision": "approve"})
    _run(client, "A second conversation")

    export = client.get("/v1/me/export").json()
    assert export["total_threads"] == 2
    assert [m["text"] for m in export["memories"]] == ["export me"]

    erased = client.delete("/v1/me/threads").json()
    assert erased["erased_count"] == 2 and erased["complete"] is True
    assert client.get("/v1/me/threads").json()["total"] == 0
    assert client.get("/v1/me/memories").json()["total"] == 0


def test_users_cannot_see_or_change_each_others_conversations(api: Api, user: Make) -> None:
    alice, bob = user("alice"), user("bob")
    thread_id = _thread_id(_run(alice, "private question"))

    assert bob.get(f"/v1/threads/{thread_id}/messages").status_code == 404
    assert bob.patch(f"/v1/threads/{thread_id}", json={"title": "mine now"}).status_code == 404
    assert bob.delete(f"/v1/threads/{thread_id}").status_code == 404
    assert (
        bob.post("/v1/agent/stream", json={"message": "hi", "thread_id": thread_id}).status_code
        == 404
    )
    assert bob.get("/v1/me/threads").json()["total"] == 0
    assert alice.get(f"/v1/threads/{thread_id}/messages").json()["total"] == 2


def test_a_token_without_the_permission_is_refused(api: Api) -> None:
    reader = api.client(f"reader-{uuid.uuid4().hex[:8]}", scope="threads:read")
    assert reader.get("/v1/me/threads").status_code == 200
    assert reader.post("/v1/agent/stream", json={"message": "hi"}).status_code == 403
    assert reader.delete("/v1/me/threads").status_code == 403
    assert reader.get("/v1/me/memories").status_code == 403


def test_bad_requests_are_rejected_before_a_run_starts(user: Make) -> None:
    client = user("invalid")
    assert client.post("/v1/agent/stream", json={"message": ""}).status_code == 422
    assert (
        client.post("/v1/agent/stream", json={"message": "hi", "thread_id": "x"}).status_code == 422
    )
    assert client.post("/v1/agent/stream", json={"message": "hi", "extra": 1}).status_code == 422
    assert client.get("/v1/threads/not-a-uuid/messages").status_code == 422
    unknown = str(uuid.uuid4())
    assert (
        client.post("/v1/agent/stream", json={"message": "hi", "thread_id": unknown}).status_code
        == 404
    )
