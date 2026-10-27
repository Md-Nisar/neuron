"""The memory routes and the user's data rights (#247, ADR 0009 decision 7)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import structlog.testing
from tests.conftest import JWT_ISSUER, HistoryEchoAgent, JwtApi, bearer

from neuron_agent.security.auth import Principal, principal_owner_key

_READ = "agent:invoke threads:read memories:read"
_WRITE = "agent:invoke threads:read threads:delete memories:write"
_ALL = "agent:invoke threads:read threads:delete memories:read memories:write"
_TEXT = "my locker code is 4417-sigma"  # noqa: S105 - test text, not a credential


@pytest.fixture
def api(jwt_api_factory: Callable[..., JwtApi], echo_agent: HistoryEchoAgent) -> JwtApi:
    return jwt_api_factory(memory_enabled=True)


def _owner(api: JwtApi, subject: str) -> str:
    principal = Principal(
        issuer=JWT_ISSUER,
        subject=subject,
        scopes=frozenset(),
        token_id=None,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    key = api.settings.identity_hash_key
    assert key is not None
    return principal_owner_key(principal, key.get_secret_value())


def _store(api: JwtApi, subject: str, *texts: str) -> list[str]:
    memory = api.service._memory
    assert memory is not None

    async def go() -> list[str]:
        return [(await memory.remember(_owner(api, subject), text)).id for text in texts]

    return asyncio.run(go())


def test_the_list_holds_only_the_callers_memories_oldest_first_with_pagination(
    api: JwtApi, make_token: Callable[..., str]
) -> None:
    _store(api, "alice", "first note", "second note", "third note")
    _store(api, "bob", "bob's note")
    alice = make_token("alice", scopes=_READ)

    page = api.client.get("/v1/me/memories?limit=2", headers=bearer(alice)).json()
    rest = api.client.get("/v1/me/memories?limit=2&offset=2", headers=bearer(alice)).json()

    assert [m["text"] for m in page["memories"]] == ["first note", "second note"]
    assert (page["total"], page["limit"], page["offset"]) == (3, 2, 0)
    assert [m["text"] for m in rest["memories"]] == ["third note"]
    assert set(page["memories"][0]) == {"id", "text", "created_at"}
    assert "bob" not in str(page) + str(rest)


def test_delete_one_removes_it_and_a_second_try_or_a_foreign_id_is_the_same_404(
    api: JwtApi, make_token: Callable[..., str]
) -> None:
    [mine] = _store(api, "alice", "mine")
    [theirs] = _store(api, "bob", "theirs")
    alice = make_token("alice", scopes=_ALL)
    bob = make_token("bob", scopes=_ALL)

    deleted = api.client.delete(f"/v1/me/memories/{mine}", headers=bearer(alice))
    again = api.client.delete(f"/v1/me/memories/{mine}", headers=bearer(alice))
    foreign = api.client.delete(f"/v1/me/memories/{theirs}", headers=bearer(alice))
    unknown = api.client.delete(f"/v1/me/memories/{'0' * 32}", headers=bearer(alice))

    assert deleted.status_code == 204
    assert [r.status_code for r in (again, foreign, unknown)] == [404, 404, 404]
    assert again.json() == foreign.json() == unknown.json() == {"detail": "memory_not_found"}
    still = api.client.get("/v1/me/memories", headers=bearer(bob)).json()
    assert [m["text"] for m in still["memories"]] == ["theirs"]


def test_erase_all_deletes_only_the_callers_memories(
    api: JwtApi, make_token: Callable[..., str]
) -> None:
    _store(api, "alice", "a1", "a2")
    _store(api, "bob", "b1")
    alice, bob = make_token("alice", scopes=_ALL), make_token("bob", scopes=_ALL)

    erased = api.client.delete("/v1/me/memories", headers=bearer(alice))

    assert (erased.status_code, erased.json()) == (200, {"erased_count": 2})
    assert api.client.get("/v1/me/memories", headers=bearer(alice)).json()["total"] == 0
    assert api.client.get("/v1/me/memories", headers=bearer(bob)).json()["total"] == 1


def test_reading_and_writing_are_separate_scopes(
    api: JwtApi, make_token: Callable[..., str]
) -> None:
    [note] = _store(api, "alice", "keep me")
    read_only, write_only = make_token("alice", scopes=_READ), make_token("alice", scopes=_WRITE)

    assert api.client.get("/v1/me/memories", headers=bearer(write_only)).status_code == 403
    assert (
        api.client.delete(f"/v1/me/memories/{note}", headers=bearer(read_only)).status_code == 403
    )
    assert api.client.delete("/v1/me/memories", headers=bearer(read_only)).status_code == 403
    assert api.client.get("/v1/me/memories", headers=bearer(read_only)).json()["total"] == 1


def test_the_routes_say_so_when_memory_is_off(
    jwt_api_factory: Callable[..., JwtApi],
    make_token: Callable[..., str],
    echo_agent: HistoryEchoAgent,
) -> None:
    api = jwt_api_factory()
    token = make_token("alice", scopes=_ALL)
    for method, path in (
        ("GET", "/v1/me/memories"),
        ("DELETE", "/v1/me/memories"),
        ("DELETE", f"/v1/me/memories/{'0' * 32}"),
    ):
        response = api.client.request(method, path, headers=bearer(token))
        assert (response.status_code, response.json()) == (404, {"detail": "memory_disabled"})


def test_export_carries_the_memories_on_the_first_page_only(
    api: JwtApi, make_token: Callable[..., str]
) -> None:
    _store(api, "alice", "one", "two")
    alice = make_token("alice", scopes=_ALL)
    api.client.post("/v1/agent/invoke", json={"message": "hi"}, headers=bearer(alice))

    first = api.client.get("/v1/me/export", headers=bearer(alice)).json()
    later = api.client.get("/v1/me/export?offset=1", headers=bearer(alice)).json()

    assert [m["text"] for m in first["memories"]] == ["one", "two"]
    assert later["memories"] == []


def test_erasing_the_users_data_deletes_the_memories_too_but_deleting_a_thread_does_not(
    api: JwtApi, make_token: Callable[..., str]
) -> None:
    _store(api, "alice", "one", "two")
    alice = make_token("alice", scopes=_ALL)
    thread = api.client.post(
        "/v1/agent/invoke", json={"message": "hi"}, headers=bearer(alice)
    ).json()["thread_id"]

    api.client.delete(f"/v1/threads/{thread}", headers=bearer(alice))
    assert api.client.get("/v1/me/memories", headers=bearer(alice)).json()["total"] == 2

    erased = api.client.delete("/v1/me/threads", headers=bearer(alice)).json()
    assert erased["erased_memory_count"] == 2
    assert api.client.get("/v1/me/memories", headers=bearer(alice)).json()["total"] == 0


def test_audit_events_carry_counts_and_ids_never_the_text(
    api: JwtApi, make_token: Callable[..., str]
) -> None:
    [note, _] = _store(api, "alice", _TEXT, "another")
    alice = make_token("alice", scopes=_ALL)

    with structlog.testing.capture_logs() as logs:
        api.client.get("/v1/me/memories", headers=bearer(alice))
        api.client.delete(f"/v1/me/memories/{note}", headers=bearer(alice))
        api.client.delete("/v1/me/memories", headers=bearer(alice))

    events: dict[str, dict[str, Any]] = {
        log["event"]: log for log in logs if log.get("audit") and log["event"].startswith("memor")
    }
    assert events["memories_read"]["count"] == 2
    assert events["memory_deleted"]["resource_id"] == note
    assert events["memories_erased"]["count"] == 1
    assert _TEXT not in str(logs)


def test_the_memory_routes_share_the_callers_request_rate_limit(
    jwt_api_factory: Callable[..., JwtApi],
    make_token: Callable[..., str],
    echo_agent: HistoryEchoAgent,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from neuron_agent.api import main as api_main
    from neuron_agent.security.rate_limiter import InMemoryTokenBucketRateLimiter

    monkeypatch.setattr(
        api_main,
        "principal_rate_limiter",
        InMemoryTokenBucketRateLimiter(capacity=2, requests_per_window=1, window_seconds=3600),
    )
    api = jwt_api_factory(memory_enabled=True, rate_limit_enabled=True)
    alice = make_token("alice", scopes=_ALL)

    statuses = [
        api.client.get("/v1/me/memories", headers=bearer(alice)).status_code,
        api.client.delete(f"/v1/me/memories/{'0' * 32}", headers=bearer(alice)).status_code,
        api.client.delete("/v1/me/memories", headers=bearer(alice)).status_code,
    ]

    assert statuses == [200, 404, 429]
