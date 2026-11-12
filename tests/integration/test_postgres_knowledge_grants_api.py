"""`GET` and `PUT /v1/knowledge/bases/{kb_id}/grants` on Postgres with real tokens (RAG-09.03).

The owner, or a role with `admin` access, replaces a base's role grants; the change counts from
the next request and each change is audited with the actor, base, role and access level (AC3).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
import structlog
from test_postgres_knowledge_api import _create, api  # noqa: F401
from test_postgres_knowledge_search_api import _ids, _search, _seed
from test_postgres_roles import RoleDatabase, role_db, roles  # noqa: F401
from tests.conftest import JwtApi, bearer

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.anyio]

_SCOPES = "knowledge:read knowledge:write knowledge:admin"


def _put(client: JwtApi, token: str, kb_id: str, grants: Any) -> Any:
    return client.client.put(
        f"/v1/knowledge/bases/{kb_id}/grants", json={"grants": grants}, headers=bearer(token)
    )


def _get(client: JwtApi, token: str, kb_id: str) -> Any:
    return client.client.get(f"/v1/knowledge/bases/{kb_id}/grants", headers=bearer(token))


async def test_the_owner_shares_and_revokes_and_every_change_is_audited(
    api: tuple[JwtApi, RoleDatabase],  # noqa: F811
    make_token: Callable[..., str],
) -> None:
    """AC1 through the API, and AC3: actor, base, role and access, no content."""
    client, db = api
    alice = make_token("alice", scopes=_SCOPES)
    bob = make_token("bob", scopes=_SCOPES, roles=["finance"])
    base = _create(client, alice, "Secret budget")
    [chunk] = await _seed(db, base["kb_id"], ["quarterly budget forecast"])

    with structlog.testing.capture_logs() as logs:
        shared = _put(client, alice, base["kb_id"], [
            {"role": "legal", "access": "read"}, {"role": "finance", "access": "read"},
        ])  # fmt: skip
        assert shared.status_code == 200, shared.text
        assert _ids(_search(client, bob, query="budget forecast")[1]) == [chunk]
        changed = _put(client, alice, base["kb_id"], [{"role": "legal", "access": "write"}])
        assert changed.status_code == 200

    assert shared.json() == {
        "grants": [{"role": "finance", "access": "read"}, {"role": "legal", "access": "read"}]
    }
    assert _get(client, alice, base["kb_id"]).json() == changed.json()
    # The revoke counts from bob's next request.
    assert _ids(_search(client, bob, query="budget forecast")[1]) == []
    events = [log for log in logs if log.get("event") == "knowledge_grant_changed"]
    assert [(e["role"], e["access"]) for e in events] == [
        ("finance", "read"),
        ("legal", "read"),
        ("finance", "none"),
        ("legal", "write"),
    ]
    for event in events:
        assert event["audit"] is True and event["outcome"] == "allowed"
        assert event["action"] == "knowledge:admin"
        assert event["resource_id"] == base["kb_id"]
        assert len(event["actor"]) == 12
    # No content: neither the base's name nor its text.
    assert "Secret budget" not in repr(logs) and "forecast" not in repr(logs)


async def test_only_the_owner_or_an_admin_role_manages_grants(
    api: tuple[JwtApi, RoleDatabase],  # noqa: F811
    make_token: Callable[..., str],
) -> None:
    client, db = api
    alice = make_token("alice", scopes=_SCOPES)
    bob = make_token("bob", scopes=_SCOPES, roles=["finance"])
    carol = make_token("carol", scopes=_SCOPES, roles=["ops"])
    no_scope = make_token("alice", scopes="knowledge:read knowledge:write")
    base = _create(client, alice, "Budget")
    kb = base["kb_id"]

    assert _put(client, no_scope, kb, []).status_code == 403  # the route's permission
    assert _put(client, bob, kb, []).status_code == 404  # cannot see it
    assert _put(client, alice, kb, [{"role": "finance", "access": "write"}]).status_code == 200
    for response in (_get(client, bob, kb), _put(client, bob, kb, [])):
        assert (response.status_code, response.json()) == (
            403,
            {"detail": "knowledge_access_denied"},
        )
    _put(client, alice, kb, [{"role": "finance", "access": "admin"}])
    # An admin role may share further and sees the grants.
    assert _put(client, bob, kb, [
        {"role": "finance", "access": "admin"}, {"role": "ops", "access": "read"},
    ]).status_code == 200  # fmt: skip
    assert [b["kb_id"] for b in client.client.get(
        "/v1/knowledge/bases", headers=bearer(carol)
    ).json()["bases"]] == [kb]  # fmt: skip
    # An admin role can drop every grant, its own too, but never the owner's access.
    assert _put(client, bob, kb, []).status_code == 200
    assert _get(client, bob, kb).status_code == 404
    assert _get(client, alice, kb).json() == {"grants": []}
    # A deleted base has no grants to edit.
    assert (
        client.client.delete(f"/v1/knowledge/bases/{kb}", headers=bearer(alice)).status_code == 202
    )
    assert _put(client, alice, kb, []).status_code == 404


@pytest.mark.parametrize(
    "grants",
    [
        [{"role": "finance", "access": "read"}, {"role": "finance", "access": "write"}],
        [{"role": "finance", "access": "owner"}],
        [{"role": " finance", "access": "read"}],
        [{"role": "fin\nance", "access": "read"}],
        [{"role": "fin\u202eance", "access": "read"}],
        [{"role": "fin\u200bance", "access": "read"}],
        [{"role": "", "access": "read"}],
        [{"role": "x" * 201, "access": "read"}],
        [{"role": "finance", "access": "read", "subject_type": "owner"}],
        [{"role": f"role-{n}", "access": "read"} for n in range(51)],
    ],
)
async def test_an_invalid_grant_list_is_422_and_changes_nothing(
    api: tuple[JwtApi, RoleDatabase],  # noqa: F811
    make_token: Callable[..., str],
    grants: list[dict[str, str]],
) -> None:
    client, _ = api
    alice = make_token("alice", scopes=_SCOPES)
    base = _create(client, alice, "Budget")
    _put(client, alice, base["kb_id"], [{"role": "legal", "access": "read"}])
    assert _put(client, alice, base["kb_id"], grants).status_code == 422
    assert _get(client, alice, base["kb_id"]).json() == {
        "grants": [{"role": "legal", "access": "read"}]
    }
