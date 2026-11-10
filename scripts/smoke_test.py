# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Post-deploy smoke test for a running Neuron API (#152, ADR 0008 decision 12).

    SMOKE_TEST_TOKEN=<access token> uv run python scripts/smoke_test.py https://api.example.com

Checks `/health/ready`, then makes one authenticated `POST /v1/agent/invoke` as the
dedicated smoke-test principal (scope `agent:invoke` only). The token is read from the
environment, sent only as a bearer header, and never printed or written to disk. Output
names the step and the HTTP status, never the URL or the token. If the deployment
persisted a thread, the script deletes it. Exit code: 0 passed, 1 failed, 2 misuse.

Optional: `SMOKE_TEST_TIMEOUT_SECONDS` (default 60) bounds each request.

`--knowledge` also checks upload -> ask -> cite (RAG-08.04) on a stack running the fake
development model, such as `docker compose up` with no provider key (the CI `local-stack` job):
it creates a knowledge base, uploads a small Markdown file, waits until it is ready, asks a
scripted `search:` turn, requires a grounded answer citing that file, and deletes the base. The
principal then needs `knowledge:read`, `knowledge:write` and `tools:search_knowledge`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

TOKEN_ENV = "SMOKE_TEST_TOKEN"  # noqa: S105  # nosec B105
TIMEOUT_ENV = "SMOKE_TEST_TIMEOUT_SECONDS"
DEFAULT_TIMEOUT_SECONDS = 60.0
# The reply is capped by the server (APP_MAX_OUTPUT_TOKENS); a one-word prompt keeps it small.
PROMPT = "Reply with the single word: ok"
# `--knowledge`: a document whose words the scripted question shares, so the lexical search
# finds it with the fake embedding provider. `search: ...` makes the fake model search and cite.
KNOWLEDGE_DOCUMENT = (
    b"# Smoke check\n\nThe Skerryvore lighthouse lamp is lit at dusk by the keeper, Morag Finlay.\n"
)
KNOWLEDGE_QUESTION = "search: Skerryvore lighthouse keeper"
INGEST_WAIT_SECONDS = 120.0
_LOOPBACK = {"localhost", "127.0.0.1", "::1"}


class SmokeFailure(Exception):
    """A failed check. The message names the step and status only."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: it would carry the bearer token to another host."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


# `ProxyHandler({})`: never route the bearer token through an HTTP(S)_PROXY.
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)


def _request(
    step: str,
    method: str,
    base_url: str,
    path: str,
    timeout: float,
    *,
    token: str | None = None,
    body: dict[str, Any] | None = None,
    upload: tuple[str, bytes] | None = None,
) -> Any:
    """Return the parsed JSON body (or None); raise `SmokeFailure` on any non-2xx or error.

    `upload` is a `(file name, Markdown bytes)` sent as the multipart field `file`."""
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    elif upload is not None:
        boundary = uuid.uuid4().hex
        name, content = upload
        data = (
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                f'filename="{name}"\r\nContent-Type: text/markdown\r\n\r\n'
            ).encode()
            + content
            + f"\r\n--{boundary}--\r\n".encode()
        )
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(  # noqa: S310  # nosec B310
        base_url + path, data=data, headers=headers, method=method
    )
    try:
        with _opener.open(request, timeout=timeout) as response:  # nosec B310
            status = response.status
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise SmokeFailure(f"{step}: HTTP {exc.code}") from None
    except TimeoutError:
        raise SmokeFailure(f"{step}: timed out") from None
    except OSError as exc:  # URLError is an OSError
        # Only the exception type: its text can carry the URL.
        reason = getattr(exc, "reason", None)
        kind = type(reason if isinstance(reason, BaseException) else exc).__name__
        if isinstance(reason, TimeoutError):
            raise SmokeFailure(f"{step}: timed out") from None
        raise SmokeFailure(f"{step}: request failed ({kind})") from None
    if not 200 <= status < 300:
        raise SmokeFailure(f"{step}: HTTP {status}")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        raise SmokeFailure(f"{step}: response is not JSON") from None


def run(base_url: str, token: str, timeout: float) -> list[str]:
    """Run the checks in order; return the passed steps or raise `SmokeFailure`."""
    base_url = base_url.rstrip("/")
    ready = _request("ready", "GET", base_url, "/health/ready", timeout)
    if not isinstance(ready, dict) or ready.get("status") != "ready":
        raise SmokeFailure("ready: body is not the ready status")
    passed = ["ready"]
    reply = _request(
        "invoke",
        "POST",
        base_url,
        "/v1/agent/invoke",
        timeout,
        token=token,
        body={"message": PROMPT},
    )
    if (
        not isinstance(reply, dict)
        or not isinstance(reply.get("answer"), str)
        or not reply["answer"].strip()
        or not isinstance(reply.get("thread_id"), str)
    ):
        raise SmokeFailure("invoke: body is not a non-empty agent answer")
    passed.append("invoke")
    _delete_thread(base_url, reply["thread_id"], token, timeout)
    passed.append("cleanup")
    return passed


def _delete_thread(base_url: str, thread_id: str, token: str, timeout: float) -> None:
    # 204: deleted. 404: nothing was stored (no checkpointer). 403: the principal holds only
    # `agent:invoke`, so it cannot delete; that is the expected case on a stateless
    # deployment, and retention prunes a persisted thread (OPERATIONS.md, smoke principal).
    path = f"/v1/threads/{thread_id}"
    try:
        _request("cleanup", "DELETE", base_url, path, timeout, token=token)
    except SmokeFailure as exc:
        if str(exc).endswith("HTTP 403"):
            print(
                "smoke_test: warning: no permission to delete the smoke thread; "
                "it remains if the deployment persists threads",
                file=sys.stderr,
            )
        elif not str(exc).endswith("HTTP 404"):
            raise SmokeFailure(f"{exc} (the smoke thread may remain)") from None


def run_knowledge(base_url: str, token: str, timeout: float) -> list[str]:
    """Upload -> ask -> cite on the fake model; the base is deleted whatever the outcome."""
    base_url = base_url.rstrip("/")
    created = _request(
        "knowledge-base",
        "POST",
        base_url,
        "/v1/knowledge/bases",
        timeout,
        token=token,
        body={"name": "Smoke check"},
    )
    if not isinstance(created, dict) or not isinstance(created.get("kb_id"), str):
        raise SmokeFailure("knowledge-base: body has no kb_id")
    kb_id = created["kb_id"]
    path = f"/v1/knowledge/bases/{kb_id}"
    try:
        passed = ["knowledge-base", *_upload_ask_cite(base_url, kb_id, token, timeout)]
    except SmokeFailure:
        # Report the check that failed, not a cleanup failure after it.
        try:
            _request("knowledge-cleanup", "DELETE", base_url, path, timeout, token=token)
        except SmokeFailure as exc:
            print(f"smoke_test: warning: {exc} (the smoke base may remain)", file=sys.stderr)
        raise
    # 202: the base and its documents are purged in the background.
    _request("knowledge-cleanup", "DELETE", base_url, path, timeout, token=token)
    return [*passed, "knowledge-cleanup"]


def _upload_ask_cite(base_url: str, kb_id: str, token: str, timeout: float) -> list[str]:
    accepted = _request(
        "upload",
        "POST",
        base_url,
        f"/v1/knowledge/bases/{kb_id}/documents",
        timeout,
        token=token,
        upload=("smoke-check.md", KNOWLEDGE_DOCUMENT),
    )
    if not isinstance(accepted, dict) or not isinstance(accepted.get("doc_id"), str):
        raise SmokeFailure("upload: body has no doc_id")
    doc_id = accepted["doc_id"]
    deadline = time.monotonic() + INGEST_WAIT_SECONDS
    while True:
        document = _request(
            "ingest", "GET", base_url, f"/v1/knowledge/documents/{doc_id}", timeout, token=token
        )
        status = document.get("status") if isinstance(document, dict) else None
        if status == "ready":
            break
        if status == "failed" or time.monotonic() > deadline:
            raise SmokeFailure(f"ingest: document is {status or 'unknown'}, not ready")
        time.sleep(1)
    reply = _request(
        "cite",
        "POST",
        base_url,
        "/v1/agent/invoke",
        timeout,
        token=token,
        body={"message": KNOWLEDGE_QUESTION, "knowledge_base_ids": [kb_id]},
    )
    citations = reply.get("citations") if isinstance(reply, dict) else None
    if (
        not isinstance(reply, dict)
        or reply.get("grounded") is not True
        or not isinstance(citations, list)
        or not any(isinstance(c, dict) and c.get("doc_id") == doc_id for c in citations)
    ):
        raise SmokeFailure("cite: the answer is not grounded in the uploaded document")
    if isinstance(reply.get("thread_id"), str):
        _delete_thread(base_url, reply["thread_id"], token, timeout)
    return ["upload", "ingest", "cite"]


def main(argv: list[str] | None = None, env: Mapping[str, str] = os.environ) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("base_url", help="API base URL, for example https://api.example.com")
    parser.add_argument(
        "--knowledge", action="store_true", help="also check upload -> ask -> cite (fake model)"
    )
    args = parser.parse_args(argv)
    token = env.get(TOKEN_ENV, "").strip()
    if not token:
        print(f"smoke_test: {TOKEN_ENV} is not set", file=sys.stderr)
        return 2
    try:
        timeout = float(env.get(TIMEOUT_ENV) or DEFAULT_TIMEOUT_SECONDS)
        if timeout <= 0:
            raise ValueError
    except ValueError:
        print(f"smoke_test: {TIMEOUT_ENV} must be a positive number", file=sys.stderr)
        return 2
    try:
        parts = urlsplit(args.base_url)
        host = parts.hostname
    except ValueError:  # malformed URL; its text is not echoed
        host = None
    if host is None or parts.scheme not in {"http", "https"}:
        print("smoke_test: the base URL must be http(s)://host", file=sys.stderr)
        return 2
    if parts.scheme == "http" and host not in _LOOPBACK:
        print("smoke_test: refusing to send a token over plain http", file=sys.stderr)
        return 2
    try:
        passed = run(args.base_url, token, timeout)
        if args.knowledge:
            passed += run_knowledge(args.base_url, token, timeout)
    except SmokeFailure as exc:
        print(f"smoke_test: FAILED {exc}", file=sys.stderr)
        return 1
    print(f"smoke_test: passed ({', '.join(passed)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
