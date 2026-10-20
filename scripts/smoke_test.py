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
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

TOKEN_ENV = "SMOKE_TEST_TOKEN"  # noqa: S105  # nosec B105
TIMEOUT_ENV = "SMOKE_TEST_TIMEOUT_SECONDS"
DEFAULT_TIMEOUT_SECONDS = 60.0
# The reply is capped by the server (APP_MAX_OUTPUT_TOKENS); a one-word prompt keeps it small.
PROMPT = "Reply with the single word: ok"
_LOOPBACK = {"localhost", "127.0.0.1", "::1"}


class SmokeFailure(Exception):
    """A failed check. The message names the step and status only."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: it would carry the bearer token to another host."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def _request(
    step: str,
    method: str,
    base_url: str,
    path: str,
    timeout: float,
    *,
    token: str | None = None,
    body: dict[str, Any] | None = None,
) -> Any:
    """Return the parsed JSON body (or None); raise `SmokeFailure` on any non-2xx or error."""
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
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
    # 204: deleted. 404: nothing was stored (no checkpointer). 403: the principal holds only
    # `agent:invoke`, so it cannot delete; that is the expected case on a stateless
    # deployment, and retention prunes a persisted thread (OPERATIONS.md, smoke principal).
    path = f"/v1/threads/{reply['thread_id']}"
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
    passed.append("cleanup")
    return passed


def main(argv: list[str] | None = None, env: Mapping[str, str] = os.environ) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("base_url", help="API base URL, for example https://api.example.com")
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
    parts = urlsplit(args.base_url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        print("smoke_test: the base URL must be http(s)://host", file=sys.stderr)
        return 2
    if parts.scheme == "http" and parts.hostname not in _LOOPBACK:
        print("smoke_test: refusing to send a token over plain http", file=sys.stderr)
        return 2
    try:
        passed = run(args.base_url, token, timeout)
    except SmokeFailure as exc:
        print(f"smoke_test: FAILED {exc}", file=sys.stderr)
        return 1
    print(f"smoke_test: passed ({', '.join(passed)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
