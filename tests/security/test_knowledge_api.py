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
        ("GET", f"{_KB}/documents", None, "knowledge:read"),
        ("POST", f"{_KB}/documents", None, "knowledge:write"),
        ("GET", f"/v1/knowledge/documents/{uuid.uuid4()}", None, "knowledge:read"),
        ("DELETE", f"/v1/knowledge/documents/{uuid.uuid4()}", None, "knowledge:write"),
        (
            "GET",
            f"/v1/knowledge/documents/{uuid.uuid4()}/chunks/{uuid.uuid4()}",
            None,
            "knowledge:read",
        ),
        ("GET", f"/v1/knowledge/documents/{uuid.uuid4()}/file", None, "knowledge:read"),
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
        ("GET", "/v1/knowledge/bases/not-a-uuid/documents", None),
        ("GET", f"{_KB}/documents?limit=101", None),
        ("GET", f"{_KB}/documents?offset=-1", None),
        ("GET", "/v1/knowledge/documents/not-a-uuid", None),
        ("DELETE", "/v1/knowledge/documents/not-a-uuid", None),
        ("GET", f"/v1/knowledge/documents/{uuid.uuid4()}/chunks/not-a-uuid", None),
        (
            "GET",
            f"/v1/knowledge/documents/{uuid.uuid4()}/chunks/{uuid.uuid4()}?neighbours=-1",
            None,
        ),
        ("GET", "/v1/knowledge/documents/not-a-uuid/file", None),
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
        "bad-id-documents",
        "limit-over-100",
        "negative-offset",
        "bad-document-id",
        "bad-document-id-delete",
        "bad-chunk-id",
        "negative-neighbours",
        "bad-document-id-file",
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
        ("GET", f"{_KB}/documents", None),
        ("POST", f"{_KB}/documents", None),
        ("GET", f"/v1/knowledge/documents/{uuid.uuid4()}", None),
    ]:
        response = jwt_api.client.request(method, path, json=body, headers=bearer(token))
        assert (response.status_code, response.json()) == (404, {"detail": "knowledge_disabled"})


@pytest.mark.parametrize("key", ["", "has space", "x" * 201, "tab\there"])
def test_an_invalid_idempotency_key_is_422(
    jwt_api: JwtApi, make_token: Callable[..., str], key: str
) -> None:
    token = make_token("alice", scopes="knowledge:write")
    response = jwt_api.client.post(
        f"{_KB}/documents",
        files={"file": ("a.txt", b"text", "text/plain")},
        headers={**bearer(token), "Idempotency-Key": key},
    )
    assert response.status_code == 422, response.text


def test_only_the_upload_route_takes_a_large_body(
    jwt_api: JwtApi, make_token: Callable[..., str]
) -> None:
    token = make_token("alice", scopes="knowledge:write")
    big = b"x" * (jwt_api.settings.max_request_body_bytes + 1)
    for path in ("/v1/knowledge/bases", f"{_KB}/documents/extra", f"{_KB}"):
        response = jwt_api.client.post(path, content=big, headers=bearer(token))
        assert response.status_code == 413, path
    # Knowledge is off here, so the upload is refused, after the body limit let it through.
    response = jwt_api.client.post(
        f"{_KB}/documents",
        content=big,
        headers={**bearer(token), "Content-Type": "multipart/form-data; boundary=x"},
    )
    assert (response.status_code, response.json()) == (404, {"detail": "knowledge_disabled"})
