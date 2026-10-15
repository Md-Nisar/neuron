"""Agent Server (`langgraph dev`) with the custom JWT auth: cross-user access must be denied."""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from langgraph_sdk import get_client

RC = Path("/var/tmp/neuron-rc")
ISSUER, AUDIENCE = "https://idp.gate.test/", "neuron-api"
KEY = ec.generate_private_key(ec.SECP256R1())
JWK = {
    **json.loads(jwt.algorithms.ECAlgorithm.to_jwk(KEY.public_key())),
    "kid": "gate",
    "alg": "ES256",
}
results: list[tuple[str, str, bool]] = []


def check(name: str, ok: bool, observed: object) -> None:
    results.append((name, str(observed), ok))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {observed}", flush=True)


class Jwks(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        body = json.dumps({"keys": [JWK]}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


def token(sub: str, scope: str = "agent:invoke threads:read threads:delete") -> str:
    now = datetime.now(UTC)
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": sub,
        "scope": scope,
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(minutes=10),
    }
    return jwt.encode(claims, KEY, algorithm="ES256", headers={"kid": "gate"})


async def checks(url: str) -> None:
    run = uuid.uuid4().hex[:8]
    alice = get_client(url=url, headers={"Authorization": f"Bearer {token(f'alice-{run}')}"})
    bob = get_client(url=url, headers={"Authorization": f"Bearer {token(f'bob-{run}')}"})
    reader = get_client(
        url=url, headers={"Authorization": f"Bearer {token(f'carol-{run}', 'threads:read')}"}
    )

    anonymous = httpx.post(f"{url}/threads", json={})
    check("unauthenticated thread creation", anonymous.status_code == 401, anonymous.status_code)

    thread = await alice.threads.create()
    owner = thread["metadata"].get("owner")
    check(
        "alice creates a thread; owner metadata is an opaque key, not the subject",
        owner is not None and "alice" not in str(owner),
        f"owner={str(owner)[:12]}...",
    )
    result = await alice.runs.wait(
        thread["thread_id"], "main", input={"messages": [{"role": "user", "content": "hi"}]}
    )
    check("alice runs the graph on her thread", isinstance(result, dict) and "answer" in result,
          f"answer={result.get('answer', {}).get('answer') if isinstance(result, dict) else result}")
    forged = await alice.runs.wait(
        thread["thread_id"], "main", input={"messages": [{"role": "user", "content": "again"}]},
        context={"permissions": ["agent:invoke", "tools:calculator", "assistants:write"]},
    )
    check("a run with forged context permissions completes (the context is ignored, not trusted)",
          isinstance(forged, dict) and "answer" in forged, "completed")

    async def status(call) -> int:
        try:
            await call
        except Exception as exc:  # noqa: BLE001 - langgraph_sdk raises httpx errors
            return getattr(getattr(exc, "response", None), "status_code", -1)
        return 200

    tid = thread["thread_id"]
    codes = {
        "read": await status(bob.threads.get(tid)),
        "state": await status(bob.threads.get_state(tid)),
        "run": await status(
            bob.runs.create(tid, "main", input={"messages": [{"role": "user", "content": "x"}]})
        ),
        "update": await status(bob.threads.update(tid, metadata={"owner": "bob"})),
        "delete": await status(bob.threads.delete(tid)),
    }
    check(
        "bob reads, inspects, runs on, updates or deletes alice's thread",
        set(codes.values()) == {404},
        codes,
    )
    searched = await bob.threads.search()
    check(
        "bob's thread search excludes alice's thread",
        tid not in [t["thread_id"] for t in searched],
        f"{len(searched)} threads visible to bob",
    )
    check("alice still sees her thread", (await alice.threads.get(tid))["thread_id"] == tid, "200")
    no_invoke = await status(reader.threads.create())
    check("a token without agent:invoke cannot create threads", no_invoke == 403, no_invoke)


def main() -> int:
    jwks = ThreadingHTTPServer(("127.0.0.1", 8768), Jwks)
    threading.Thread(target=jwks.serve_forever, daemon=True).start()
    (RC / ".env").write_text(
        "\n".join(
            [
                "APP_ENV=development",
                "APP_AUTH_MODE=jwt",
                f"APP_AUTH_ISSUER={ISSUER}",
                f"APP_AUTH_AUDIENCE={AUDIENCE}",
                "APP_AUTH_JWKS_URL=http://127.0.0.1:8768/jwks.json",
                "APP_IDENTITY_HASH_KEY=" + "a" * 40,
                "OPENAI_API_KEY=",
            ]
        )
        + "\n"
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("APP_") and "OPENAI" not in k}
    log = open("/var/tmp/gate/langgraph-dev.log", "wb")
    server = subprocess.Popen(
        ["uv", "run", "langgraph", "dev", "--no-browser", "--no-reload", "--port", "2024"],
        cwd=RC,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    try:
        url = None
        for _ in range(180):
            found = re.search(r"API: \S*?(http://127\.0\.0\.1:\d+)", Path("/var/tmp/gate/langgraph-dev.log").read_text(errors="replace"))
            if found:
                url = found.group(1)
                try:
                    if httpx.get(f"{url}/ok").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
            time.sleep(1)
        else:
            raise RuntimeError("langgraph dev did not become ready")
        print("langgraph dev at", url, flush=True)
        asyncio.run(checks(url))
    finally:
        server.terminate()
        server.wait(timeout=30)
    print(f"{sum(ok for *_, ok in results)}/{len(results)} checks passed")
    return 0 if all(ok for *_, ok in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
