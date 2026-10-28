"""Conversation titles: owner-scoped, removed with the thread, and never logged (ADR 0011)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
import structlog.testing
from tests.conftest import HistoryEchoAgent, JwtApi, bearer

from neuron_agent.persistence.retention import prune_threads
from neuron_agent.persistence.thread_meta import TITLE_MAX_CHARS

_FIRST = "  plan   my\n trip to Lisbon  "


@pytest.fixture
def api(jwt_api_factory: Callable[..., JwtApi], echo_agent: HistoryEchoAgent) -> JwtApi:
    return jwt_api_factory()


def _ask(api: JwtApi, token: str, message: str, thread_id: str | None = None) -> dict[str, Any]:
    body = {"message": message, **({"thread_id": thread_id} if thread_id else {})}
    response = api.client.post("/v1/agent/invoke", json=body, headers=bearer(token))
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


def _owner_key_of(api: JwtApi, title: str) -> str:
    """The owner key a stored title is filed under (the HMAC of the subject, never the subject)."""
    entries = api.service._persistence.thread_titles._titles  # type: ignore[attr-defined]
    (key,) = {owner for (owner, _), stored in entries.items() if stored == title}
    return str(key)


def _titles(api: JwtApi, token: str) -> dict[str, str | None]:
    listing = api.client.get("/v1/me/threads", headers=bearer(token)).json()
    return {t["thread_id"]: t["title"] for t in listing["threads"]}


def test_a_new_thread_is_titled_from_its_first_message_and_a_reply_does_not_rename_it(
    api: JwtApi, make_token: Callable[..., str]
) -> None:
    alice = make_token("alice")
    thread = _ask(api, alice, _FIRST)["thread_id"]
    _ask(api, alice, "something else entirely", thread)

    assert _titles(api, alice) == {thread: "plan my trip to Lisbon"}


def test_a_long_first_message_is_cut_to_the_title_limit(
    api: JwtApi, make_token: Callable[..., str]
) -> None:
    alice = make_token("alice")
    thread = _ask(api, alice, "x" * 300)["thread_id"]

    assert _titles(api, alice) == {thread: "x" * TITLE_MAX_CHARS}


def test_a_streamed_run_is_titled_too(api: JwtApi, make_token: Callable[..., str]) -> None:
    alice = make_token("alice")
    response = api.client.post(
        "/v1/agent/stream", json={"message": "streamed hello"}, headers=bearer(alice)
    )
    assert response.status_code == 200, response.text

    assert list(_titles(api, alice).values()) == ["streamed hello"]


def test_titles_are_owner_scoped_and_exported(api: JwtApi, make_token: Callable[..., str]) -> None:
    alice, bob = make_token("alice"), make_token("bob")
    mine = _ask(api, alice, "alice private topic")["thread_id"]
    _ask(api, bob, "bob private topic")

    export = api.client.get("/v1/me/export", headers=bearer(alice)).json()

    assert [(t["thread_id"], t["title"]) for t in export["threads"]] == [
        (mine, "alice private topic")
    ]
    assert "bob private" not in str(_titles(api, alice)) + str(export)
    assert "alice private" not in str(_titles(api, bob))


def test_deleting_a_thread_removes_its_title(api: JwtApi, make_token: Callable[..., str]) -> None:
    alice = make_token("alice")
    gone = _ask(api, alice, "to be deleted")["thread_id"]
    kept = _ask(api, alice, "to be kept")["thread_id"]

    assert api.client.delete(f"/v1/threads/{gone}", headers=bearer(alice)).status_code == 204

    assert _titles(api, alice) == {kept: "to be kept"}
    assert [t for (_, t) in api.service._persistence.thread_titles._titles] == [kept]  # type: ignore[attr-defined]


def test_erasing_a_users_data_removes_their_titles_and_only_theirs(
    api: JwtApi, make_token: Callable[..., str]
) -> None:
    alice, bob = make_token("alice"), make_token("bob")
    _ask(api, alice, "alice topic")
    theirs = _ask(api, bob, "bob topic")["thread_id"]

    # A title whose thread is already gone (a crash between the two deletes) goes as well.
    asyncio.run(
        api.service._persistence.thread_titles.set_if_absent(
            _owner_key_of(api, "alice topic"), "orphan", "left"
        )
    )
    assert api.client.delete("/v1/me/threads", headers=bearer(alice)).json()["complete"]

    assert _titles(api, alice) == {}
    assert _titles(api, bob) == {theirs: "bob topic"}
    assert len(api.service._persistence.thread_titles._titles) == 1  # type: ignore[attr-defined]


def test_retention_removes_the_titles_of_the_threads_it_prunes(
    api: JwtApi, make_token: Callable[..., str]
) -> None:
    alice = make_token("alice")
    _ask(api, alice, "old conversation")

    asyncio.run(prune_threads(api.service._persistence, older_than=timedelta(0)))

    assert _titles(api, alice) == {}
    assert api.service._persistence.thread_titles._titles == {}  # type: ignore[attr-defined]


def test_a_title_never_reaches_the_logs(api: JwtApi, make_token: Callable[..., str]) -> None:
    alice = make_token("alice")
    marker = "zebra-marker-4821"

    with structlog.testing.capture_logs() as logs:
        thread = _ask(api, alice, f"discuss {marker}")["thread_id"]
        api.client.get("/v1/me/threads", headers=bearer(alice))
        api.client.get("/v1/me/export", headers=bearer(alice))
        api.client.delete(f"/v1/threads/{thread}", headers=bearer(alice))

    assert marker not in repr(logs)


def test_a_failing_title_store_does_not_fail_the_run(
    api: JwtApi, make_token: Callable[..., str], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(*_: object) -> None:
        raise RuntimeError("database down")

    monkeypatch.setattr(api.service._persistence.thread_titles, "set_if_absent", broken)
    alice = make_token("alice")

    with structlog.testing.capture_logs() as logs:
        body = _ask(api, alice, "still answered")

    assert body["status"] == "completed"
    assert [log["error_type"] for log in logs if log["event"] == "thread_title_failed"] == [
        "RuntimeError"
    ]
