"""The knowledge base routes before they reach the database (RAG-03.01).

Ownership, the tombstone and the purge job need Postgres: `test_postgres_knowledge_api.py`.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

import pytest
from tests.conftest import JwtApi, bearer

from neuron_agent.api import main as api_main
from neuron_agent.errors.base import (
    DownloadBusyError,
    KnowledgeDocumentNotFoundError,
    UploadBusyError,
)

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
        ("POST", "/v1/knowledge/search", {"query": "q"}, "knowledge:read"),
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
        ("POST", "/v1/knowledge/search", {"query": "q" * 501}),
        ("POST", "/v1/knowledge/search", {"query": " \n "}),
        ("POST", "/v1/knowledge/search", {"query": ""}),
        ("POST", "/v1/knowledge/search", {"query": "q", "owner_key": "a" * 64}),
        ("POST", "/v1/knowledge/search", {"query": "q", "kb_ids": []}),
        ("POST", "/v1/knowledge/search", {"query": "q", "kb_ids": [str(uuid.uuid4())] * 11}),
        ("POST", "/v1/knowledge/search", {"query": "q", "kb_ids": ["not-a-uuid"]}),
        ("POST", "/v1/knowledge/search", {"query": "q", "limit": 11}),
        ("POST", "/v1/knowledge/search", {"query": "q", "limit": 0}),
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
        "search-query-over-500",
        "search-blank-query",
        "search-empty-query",
        "search-owner-field",
        "search-no-kb-ids",
        "search-over-10-kb-ids",
        "search-bad-kb-id",
        "search-limit-over-10",
        "search-limit-0",
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
        ("POST", "/v1/knowledge/search", {"query": "q"}),
    ]:
        response = jwt_api.client.request(method, path, json=body, headers=bearer(token))
        assert (response.status_code, response.json()) == (404, {"detail": "knowledge_disabled"})


def test_with_knowledge_off_data_rights_leave_knowledge_out(
    jwt_api: JwtApi, make_token: Callable[..., str]
) -> None:
    """RAG-07.01: erase-everything and export work as before, with an empty knowledge part."""
    token = make_token("alice", scopes="threads:read threads:delete")
    erased = jwt_api.client.delete("/v1/me/knowledge", headers=bearer(token))
    assert (erased.status_code, erased.json()) == (404, {"detail": "knowledge_disabled"})
    everything = jwt_api.client.delete("/v1/me/threads", headers=bearer(token)).json()
    assert (everything["knowledge"], everything["complete"]) == (None, True)
    exported = jwt_api.client.get("/v1/me/export", headers=bearer(token)).json()
    assert exported["knowledge_bases"] == []


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


class _OneFile:
    """Stands in for `KnowledgeBases.file`: one readable document, anything else is `404`."""

    def __init__(self, doc_id: uuid.UUID) -> None:
        self.doc_id = doc_id

    async def file(self, owner_key: str, doc_id: uuid.UUID) -> tuple[str, str, bytes]:
        if doc_id != self.doc_id:
            raise KnowledgeDocumentNotFoundError("knowledge document not found")
        return "notes.txt", "text/plain", b"hello"


@pytest.fixture
def download_slots(monkeypatch: pytest.MonkeyPatch) -> api_main._MemorySlots:
    slots = api_main._MemorySlots(lambda: 1, DownloadBusyError)
    monkeypatch.setattr(api_main, "_download_slots", slots)
    return slots


def test_a_download_frees_its_slot_once_sent_or_refused(
    jwt_api: JwtApi,
    make_token: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
    download_slots: api_main._MemorySlots,
) -> None:
    doc_id = uuid.uuid4()
    monkeypatch.setattr(api_main, "knowledge", _OneFile(doc_id))
    auth = bearer(make_token("alice", scopes="knowledge:read"))
    for _ in range(2):  # with one slot, the second download needs the first one freed
        sent = jwt_api.client.get(f"/v1/knowledge/documents/{doc_id}/file", headers=auth)
        assert (sent.status_code, sent.content) == (200, b"hello")
        missing = jwt_api.client.get(f"/v1/knowledge/documents/{uuid.uuid4()}/file", headers=auth)
        assert missing.status_code == 404
    assert download_slots.in_flight == 0


def test_a_download_over_the_process_cap_is_429(
    jwt_api: JwtApi,
    make_token: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
    download_slots: api_main._MemorySlots,
) -> None:
    doc_id = uuid.uuid4()
    monkeypatch.setattr(api_main, "knowledge", _OneFile(doc_id))
    download_slots.acquire("another owner")
    response = jwt_api.client.get(
        f"/v1/knowledge/documents/{doc_id}/file",
        headers=bearer(make_token("alice", scopes="knowledge:read")),
    )
    assert (response.status_code, response.json()) == (429, {"detail": "download_busy"})
    assert response.headers["retry-after"] == "1"
    assert download_slots.in_flight == 1


def test_one_owner_cannot_hold_every_transfer_slot() -> None:
    slots = api_main._MemorySlots(lambda: 4, UploadBusyError)
    slots.acquire("alice")
    slots.acquire("alice")
    with pytest.raises(UploadBusyError):
        slots.acquire("alice")
    slots.acquire("bob")  # another tenant still gets a slot
    slots.release("alice")
    slots.acquire("alice")
    assert slots.in_flight == 3


def test_transfer_slots_are_freed_when_the_body_fails() -> None:
    slots = api_main._MemorySlots(lambda: 1, UploadBusyError)
    with pytest.raises(RuntimeError), slots.take("alice"):
        raise RuntimeError
    with slots.take("bob"):
        assert slots.in_flight == 1
    assert slots.in_flight == 0
