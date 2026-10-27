"""Cross-user isolation, end to end with real tokens through the HTTP API (#61).

The BOLA matrix runs every `/v1/*` route as the owner and as other callers. A thread that
belongs to someone else must be indistinguishable from one that doesn't exist, and no
response to another caller may contain the owner's conversation content.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import anyio
import httpx
import pytest
import structlog.testing
from fastapi.routing import APIRoute
from langchain_core.messages import HumanMessage
from tests.conftest import JWT_ISSUER, HistoryEchoAgent, JwtApi, JwtClock, bearer

from neuron_agent.api import main as api_main
from neuron_agent.schemas.agent import AgentRequest
from neuron_agent.security.auth import Principal

_MARKER = "alice-secret-7f3c"  # conversation content that must never cross users
_APPROVAL_ID = "0123456789abcdef0123456789abcdef"  # nothing is pending under this ID
_MEMORY_ID = "fedcba9876543210fedcba9876543210"  # no memory has this ID


def _not_found(path: str) -> dict[str, str]:
    """The one 404 body for a thread or approval the caller cannot reach."""
    return {"detail": "approval_not_found" if "/approvals/" in path else "thread_not_found"}


@pytest.fixture
def jwt_api(jwt_api_factory: Callable[..., JwtApi], echo_agent: HistoryEchoAgent) -> JwtApi:
    """Memory is on here, so the `/v1/me/memories` routes in the matrix are really served."""
    return jwt_api_factory(memory_enabled=True)


def _parse_sse(body: str) -> list[tuple[str, dict[str, Any]]]:
    events = []
    for block in body.replace("\r\n", "\n").strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "event" in fields:
            events.append((fields["event"], json.loads(fields["data"])))
    return events


def _route_requests(
    thread_id: str, approval_id: str = _APPROVAL_ID, memory_id: str = _MEMORY_ID
) -> list[tuple[str, str, dict[str, Any] | None]]:
    """One request per `/v1/*` route, aimed at `thread_id` wherever the route takes one."""
    return [
        ("POST", "/v1/agent/invoke", {"message": "probe", "thread_id": thread_id}),
        ("POST", "/v1/agent/stream", {"message": "probe", "thread_id": thread_id}),
        ("GET", f"/v1/threads/{thread_id}/messages", None),
        ("DELETE", f"/v1/threads/{thread_id}", None),
        ("POST", f"/v1/threads/{thread_id}/approvals/{approval_id}", {"decision": "approve"}),
        (
            "POST",
            f"/v1/threads/{thread_id}/approvals/{approval_id}/stream",
            {"decision": "approve"},
        ),
        ("GET", "/v1/me/threads", None),
        ("GET", "/v1/me/export", None),
        ("GET", "/v1/me/memories", None),
        ("DELETE", f"/v1/me/memories/{memory_id}", None),
        ("DELETE", "/v1/me/memories", None),
        ("DELETE", "/v1/me/threads", None),
    ]


def test_matrix_covers_every_v1_route() -> None:
    declared = {
        (method, route.path)
        for route in api_main.app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/v1/")
        for method in route.methods
    }
    probe = "{thread_id}"
    covered = {
        (method, path) for method, path, _ in _route_requests(probe, "{approval_id}", "{memory_id}")
    }
    assert covered == declared


def _owned_thread(api: JwtApi, token: str) -> str:
    response = api.client.post(
        "/v1/agent/invoke", json={"message": f"remember {_MARKER}"}, headers=bearer(token)
    )
    assert response.status_code == 200, response.text
    return str(response.json()["thread_id"])


def _history(api: JwtApi, thread_id: str, token: str) -> httpx.Response:
    return api.client.get(f"/v1/threads/{thread_id}/messages", headers=bearer(token))


@pytest.mark.parametrize(
    "intruder",
    [
        pytest.param({"sub": "mallory"}, id="other-user"),
        pytest.param({"sub": "ALICE"}, id="case-variant-subject"),
        pytest.param({"sub": "alice "}, id="padded-subject"),
    ],
)
def test_other_user_cannot_reach_owned_thread_on_any_route(
    jwt_api: JwtApi, make_token: Callable[..., str], intruder: dict[str, Any]
) -> None:
    alice = make_token("alice")
    intruder_token = make_token(**intruder)
    thread_id = _owned_thread(jwt_api, alice)
    unknown = str(uuid.uuid4())

    # Request-supplied identity fields naming the owner must not matter in JWT mode.
    spoofed = {**bearer(intruder_token), "X-User-Id": "alice"}
    for (method, path, body), (_, unknown_path, unknown_body) in zip(
        _route_requests(thread_id), _route_requests(unknown), strict=True
    ):
        if body is not None and "/approvals/" not in path:  # that body takes no identity field
            body = {**body, "user_id": "alice"}
            unknown_body = {**unknown_body, "user_id": "alice"} if unknown_body else None
        response = jwt_api.client.request(method, path, json=body, headers=spoofed)
        assert _MARKER not in response.text, (method, path)
        if unknown_path == path and unknown_body == body:
            # A caller-scoped `/v1/me/*` route: it succeeds, scoped to the intruder only. (A
            # memory ID is not a thread: nobody has the probe ID, so the answer is the one 404.)
            expected = 404 if "/memories/" in path else 200
            assert response.status_code == expected, (method, path, response.text)
            assert thread_id not in response.text, (method, path)
            continue
        baseline = jwt_api.client.request(method, unknown_path, json=unknown_body, headers=spoofed)
        # Another user's thread is indistinguishable from a thread that doesn't exist.
        assert response.status_code == baseline.status_code == 404, (method, path)
        assert response.json() == baseline.json() == _not_found(path)

    # The intruder's erase-all and the failed delete left the owner's thread intact.
    history = _history(jwt_api, thread_id, alice)
    assert history.status_code == 200
    assert _MARKER in history.text


def test_owner_reaches_own_thread_on_every_route(
    jwt_api: JwtApi, make_token: Callable[..., str]
) -> None:
    alice = make_token("alice")
    thread_id = _owned_thread(jwt_api, alice)
    for method, path, body in _route_requests(thread_id):
        if method == "DELETE":
            continue  # Deletion is checked last, below.
        response = jwt_api.client.request(method, path, json=body, headers=bearer(alice))
        if "/approvals/" in path:
            # The owner reaches the route; nothing is pending under this ID (the pending case
            # is tested in test_approval_api.py).
            assert (response.status_code, response.json()) == (404, _not_found(path))
            continue
        assert response.status_code == 200, (method, path, response.text)
    listing = jwt_api.client.get("/v1/me/threads", headers=bearer(alice)).json()
    assert [t["thread_id"] for t in listing["threads"]] == [thread_id]
    export = jwt_api.client.get("/v1/me/export", headers=bearer(alice))
    assert _MARKER in export.text

    deleted = jwt_api.client.delete(f"/v1/threads/{thread_id}", headers=bearer(alice))
    assert deleted.status_code == 204
    _owned_thread(jwt_api, alice)
    erased = jwt_api.client.delete("/v1/me/threads", headers=bearer(alice))
    assert erased.json() == {
        "erased_count": 1,
        "skipped_busy_count": 0,
        "erased_memory_count": 0,
        "complete": True,
    }


def test_same_subject_from_another_issuer_is_not_the_owner(
    jwt_api: JwtApi, make_token: Callable[..., str]
) -> None:
    """A token for `alice` minted by another issuer, even signed by a trusted key."""
    alice = make_token("alice")
    thread_id = _owned_thread(jwt_api, alice)
    impostor = make_token("alice", iss="https://other-issuer.example.test")
    lookalike = make_token("alice", iss=JWT_ISSUER + "/")

    for token in (impostor, lookalike):
        for method, path, body in _route_requests(thread_id):
            response = jwt_api.client.request(method, path, json=body, headers=bearer(token))
            assert response.status_code == 401, (method, path)
            assert _MARKER not in response.text
    assert _MARKER in _history(jwt_api, thread_id, alice).text


def test_token_expiring_mid_session_loses_access_on_every_route(
    jwt_api: JwtApi, make_token: Callable[..., str], jwt_clock: type[JwtClock]
) -> None:
    alice = make_token("alice", exp=timedelta(minutes=5))
    renewed = make_token("alice", exp=timedelta(minutes=30))
    thread_id = _owned_thread(jwt_api, alice)
    assert _history(jwt_api, thread_id, alice).status_code == 200

    jwt_clock.offset = timedelta(minutes=10)
    for method, path, body in _route_requests(thread_id):
        response = jwt_api.client.request(method, path, json=body, headers=bearer(alice))
        assert response.status_code == 401, (method, path)
        assert response.json() == {"detail": "authentication_error"}

    # A fresh token for the same principal resumes the same thread, untouched.
    history = _history(jwt_api, thread_id, renewed)
    assert history.status_code == 200
    assert history.json()["total"] == 2


@pytest.mark.anyio
async def test_busy_thread_of_another_user_is_still_not_found(
    jwt_api: JwtApi, make_token: Callable[..., str]
) -> None:
    """A run in flight must not turn another user's 404 into a revealing 409."""
    alice, mallory = make_token("alice"), make_token("mallory")
    thread_id = _owned_thread(jwt_api, alice)
    principal = await _principal(alice)
    run = await jwt_api.service.prepare(
        AgentRequest(message="hold", thread_id=thread_id), streaming=True, principal=principal
    )
    try:
        for path in ("/v1/agent/invoke", "/v1/agent/stream"):
            body = {"message": "probe", "thread_id": thread_id}
            busy = jwt_api.client.post(path, json=body, headers=bearer(alice))
            assert busy.status_code == 409, path
            foreign = jwt_api.client.post(path, json=body, headers=bearer(mallory))
            assert foreign.status_code == 404, path
            assert foreign.json() == {"detail": "thread_not_found"}
    finally:
        await run.lease.release()


async def _principal(token: str) -> Principal:
    return await api_main.auth_verifier.verify(f"Bearer {token}")


_ROUTE_PERMISSION = {
    "/v1/agent/invoke": "agent:invoke",
    "/v1/agent/stream": "agent:invoke",
    "/v1/threads/{id}/messages": "threads:read",
    "/v1/threads/{id}": "threads:delete",
    "/v1/me/threads:GET": "threads:read",
    "/v1/me/export": "threads:read",
    "/v1/me/threads:DELETE": "threads:delete",
}


def _permission(method: str, path: str, thread_id: str) -> str:
    key = path.replace(thread_id, "{id}")
    return _ROUTE_PERMISSION.get(f"{key}:{method}", _ROUTE_PERMISSION.get(key, ""))


@pytest.mark.parametrize("revoked", ["agent:invoke", "threads:read", "threads:delete"])
def test_revoked_permission_is_enforced_on_the_next_token(
    jwt_api: JwtApi, make_token: Callable[..., str], revoked: str
) -> None:
    granted = {"agent:invoke", "threads:read", "threads:delete"}
    alice = make_token("alice", scopes=" ".join(sorted(granted)))
    thread_id = _owned_thread(jwt_api, alice)
    reduced = make_token("alice", scopes=" ".join(sorted(granted - {revoked})))

    checked = 0
    for method, path, body in _route_requests(thread_id):
        if _permission(method, path, thread_id) != revoked:
            continue
        response = jwt_api.client.request(method, path, json=body, headers=bearer(reduced))
        assert response.status_code == 403, (method, path)
        assert response.json() == {"detail": "authorization_error"}
        assert f'scope="{revoked}"' in response.headers["www-authenticate"]
        checked += 1
    assert checked == {"agent:invoke": 2, "threads:read": 3, "threads:delete": 2}[revoked]
    # A denied delete or erase removed nothing.
    assert _MARKER in _history(jwt_api, thread_id, alice).text


class _SlowEchoAgent(HistoryEchoAgent):
    """Holds each run open so two users' runs overlap; tracks the peak overlap."""

    def __init__(self) -> None:
        super().__init__()
        self.active = 0
        self.peak = 0

    async def ainvoke(
        self, inputs: dict[str, Any], *, config: dict[str, Any], context: Any = None
    ) -> dict[str, Any]:
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            await anyio.sleep(0.2)
            return await super().ainvoke(inputs, config=config, context=context)
        finally:
            self.active -= 1


@pytest.mark.anyio
async def test_parallel_users_never_observe_each_others_streams_or_tokens(
    jwt_api_factory: Callable[..., JwtApi],
    make_token: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from neuron_agent.graphs import main_graph

    agent = _SlowEchoAgent()
    monkeypatch.setattr(main_graph, "build_agent", lambda settings: agent)
    jwt_api_factory()  # installs the JWT-mode settings, verifier and service
    users = {name: make_token(name) for name in ("alice", "bob")}
    markers = {name: f"{name}-marker-{uuid.uuid4().hex[:8]}" for name in users}
    bodies: dict[str, str] = {}

    transport = httpx.ASGITransport(app=api_main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Seed two threads per user (a thread runs one turn at a time), then stream a
        # follow-up turn on all four at once.
        threads: dict[str, list[str]] = {name: [] for name in users}
        for name, token in users.items():
            for _ in range(2):
                seeded = await client.post(
                    "/v1/agent/invoke", json={"message": markers[name]}, headers=bearer(token)
                )
                threads[name].append(seeded.json()["thread_id"])

        async def stream(name: str, turn: int) -> None:
            response = await client.post(
                "/v1/agent/stream",
                json={"message": f"{markers[name]} turn {turn}", "thread_id": threads[name][turn]},
                headers=bearer(users[name]),
            )
            assert response.status_code == 200
            bodies[f"{name}-{turn}"] = response.text

        with structlog.testing.capture_logs() as logs:
            async with anyio.create_task_group() as group:
                for turn in range(2):
                    for name in users:
                        group.start_soon(stream, name, turn)

    assert agent.peak >= 2, "runs did not overlap; the test proves nothing"
    for key, body in bodies.items():
        name, turn = key.split("-")
        other = next(n for n in users if n != name)
        events = _parse_sse(body)
        assert [event for event, _ in events][0] == "run_started"
        assert [event for event, _ in events][-2:] == ["final", "done"]
        assert events[0][1]["thread_id"] == threads[name][int(turn)]
        final = events[-2][1]
        assert final["thread_id"] == threads[name][int(turn)]
        assert markers[name] in final["answer"]
        assert markers[other] not in body, f"{key} observed {other}'s conversation"
        assert not any(thread_id in body for thread_id in threads[other])
        assert not any(token in body for token in users.values())
    # Each model call saw only its own user's turns: two on a stream, one on a seed.
    for call in agent.calls:
        human = " ".join(str(m.content) for m in call if isinstance(m, HumanMessage))
        assert sum(marker in human for marker in markers.values()) == 1
    # Neither bearer token reached the logs (which did capture the runs).
    assert any(entry["event"] == "agent_execution_started" for entry in logs)
    rendered = json.dumps(logs, default=str)
    assert not any(token in rendered for token in users.values())
