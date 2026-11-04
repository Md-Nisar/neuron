"""The knowledge base routes before they reach the database (RAG-03.01).

Ownership, the tombstone and the purge job need Postgres: `test_postgres_knowledge_api.py`.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

import pytest
from tests.conftest import JwtApi, bearer

_KB = f"/v1/knowledge/bases/{uuid.uuid4()}"


@pytest.mark.parametrize(
    ("method", "path", "body", "permission"),
    [
        ("GET", "/v1/knowledge/bases", None, "knowledge:read"),
        ("POST", "/v1/knowledge/bases", {"name": "kb"}, "knowledge:write"),
        ("PATCH", _KB, {"name": "kb"}, "knowledge:write"),
        ("DELETE", _KB, None, "knowledge:write"),
    ],
)
def test_a_token_without_the_routes_permission_is_refused(
    jwt_api: JwtApi,
    make_token: Callable[..., str],
    method: str,
    path: str,
    body: dict[str, str] | None,
    permission: str,
) -> None:
    other = "knowledge:read" if permission == "knowledge:write" else "knowledge:write"
    token = make_token("alice", scopes=f"agent:invoke {other}")
    response = jwt_api.client.request(method, path, json=body, headers=bearer(token))
    assert (response.status_code, response.json()) == (403, {"detail": "authorization_error"})
    assert f'scope="{permission}"' in response.headers["www-authenticate"]


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", "/v1/knowledge/bases", {"name": "kb", "owner_key": "a" * 64}),
        ("POST", "/v1/knowledge/bases", {"name": "kb", "processing": "anywhere"}),
        ("POST", "/v1/knowledge/bases", {"name": "   "}),
        ("POST", "/v1/knowledge/bases", {"name": "x" * 81}),
        ("POST", "/v1/knowledge/bases", {"name": "a" + chr(0x202E) + "b"}),
        ("POST", "/v1/knowledge/bases", {}),
        ("PATCH", _KB, {"name": "kb", "processing": "hosted"}),
        ("PATCH", "/v1/knowledge/bases/not-a-uuid", {"name": "kb"}),
        ("DELETE", "/v1/knowledge/bases/not-a-uuid", None),
    ],
    ids=[
        "unknown-field",
        "unknown-processing",
        "blank-name",
        "long-name",
        "invisible-character",
        "no-name",
        "rename-only",
        "bad-id",
        "bad-id-delete",
    ],
)
def test_an_invalid_request_is_422(
    jwt_api: JwtApi,
    make_token: Callable[..., str],
    method: str,
    path: str,
    body: dict[str, str] | None,
) -> None:
    token = make_token("alice", scopes="knowledge:read knowledge:write")
    response = jwt_api.client.request(method, path, json=body, headers=bearer(token))
    assert response.status_code == 422, response.text


def test_with_knowledge_off_every_route_is_404(
    jwt_api: JwtApi, make_token: Callable[..., str]
) -> None:
    token = make_token("alice", scopes="knowledge:read knowledge:write")
    for method, path, body in [
        ("GET", "/v1/knowledge/bases", None),
        ("POST", "/v1/knowledge/bases", {"name": "kb"}),
        ("PATCH", _KB, {"name": "kb"}),
        ("DELETE", _KB, None),
    ]:
        response = jwt_api.client.request(method, path, json=body, headers=bearer(token))
        assert (response.status_code, response.json()) == (404, {"detail": "knowledge_disabled"})
