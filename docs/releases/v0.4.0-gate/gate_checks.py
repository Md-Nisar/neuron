"""v0.4.0 release gate (#63): real servers, real HTTP, a controllable JWKS and nginx."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import ec

REPO = "/home/user/neuron"
GATE = Path("/var/tmp/gate")
DSN = "postgresql://postgres@/neuron_test?host=/var/tmp/neuron-pg&port=55432"
ISSUER = "https://idp.gate.test/"
AUDIENCE = "neuron-api"
ORIGIN = "https://app.example.com"
ALL = "agent:invoke threads:read threads:delete tools:calculator"
RUN = uuid.uuid4().hex[:8]
PROXY = "http://127.0.0.1:8080"

results: list[tuple[str, str, bool]] = []
secrets_seen: set[str] = set()  # tokens, subjects and prompts that must never be logged


def check(name: str, ok: bool, observed: Any) -> None:
    results.append((name, str(observed), ok))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {observed}", flush=True)


# --- identity provider double -------------------------------------------------------

KEYS = {
    "k1": ec.generate_private_key(ec.SECP256R1()),
    "k2": ec.generate_private_key(ec.SECP256R1()),
}
published = {"k1"}
current = {"kid": "k1"}  # the key the IdP signs new tokens with


def jwks() -> bytes:
    keys = []
    for kid in sorted(published):
        jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(KEYS[kid].public_key()))
        keys.append({**jwk, "kid": kid, "alg": "ES256", "use": "sig"})
    return json.dumps({"keys": keys}).encode()


class JwksHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        body = jwks()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:
        pass


jwks_server: ThreadingHTTPServer | None = None


def jwks_up() -> None:
    global jwks_server
    jwks_server = ThreadingHTTPServer(("127.0.0.1", 8766), JwksHandler)
    threading.Thread(target=jwks_server.serve_forever, daemon=True).start()


def jwks_down() -> None:
    assert jwks_server is not None
    jwks_server.shutdown()
    jwks_server.server_close()


def token(sub: str, *, kid: str | None = None, scope: str = ALL) -> str:
    kid = kid or current["kid"]
    now = datetime.now(UTC)
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": sub,
        "scope": scope,
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(minutes=10),
        "jti": str(uuid.uuid4()),
    }
    value = jwt.encode(claims, KEYS[kid], algorithm="ES256", headers={"kid": kid})
    secrets_seen.update({value, value.split(".")[2]})
    return value


def auth(value: str, **extra: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {value}", **extra}


def user(name: str) -> str:
    sub = f"{name}-{RUN}"
    secrets_seen.add(sub)
    return sub


def prompt(text: str) -> dict[str, str]:
    marker = f"{text}-{RUN}"
    secrets_seen.add(marker)
    return {"message": marker}


# --- servers ------------------------------------------------------------------------

BASE_ENV = {
    "APP_ENV": "development",
    "APP_AUTH_MODE": "jwt",
    "APP_AUTH_ISSUER": ISSUER,
    "APP_AUTH_AUDIENCE": AUDIENCE,
    "APP_AUTH_JWKS_URL": "http://127.0.0.1:8766/jwks.json",
    "APP_AUTH_ISSUER_ID": "gate",
    "APP_AUTH_JWKS_CACHE_SECONDS": "2",
    "APP_AUTH_AUDIT_SUCCESS_ENABLED": "true",
    "APP_IDENTITY_HASH_KEY": "g" * 40,
    "APP_CHECKPOINTER": "postgres",
    "APP_POSTGRES_DSN": DSN,
    "APP_CHECKPOINTER_SETUP_ON_STARTUP": "true",
    "APP_CORS_ALLOWED_ORIGINS": json.dumps([ORIGIN]),
    "APP_RATE_LIMIT_ENABLED": "false",
}
servers: list[subprocess.Popen[bytes]] = []


def start_api(port: int, log: str, **overrides: str) -> str:
    env = {k: v for k, v in os.environ.items() if not k.endswith("OPENAI_API_KEY")}
    env.update(BASE_ENV, GATE_PORT=str(port), **overrides)
    out = open(GATE / log, "wb")
    process = subprocess.Popen(
        ["uv", "run", "--project", REPO, "python", str(GATE / "gate_server.py")],
        cwd=GATE,
        env=env,
        stdout=out,
        stderr=subprocess.STDOUT,
    )
    servers.append(process)
    url = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            if httpx.get(f"{url}/health/live").status_code == 200:
                return url
        except httpx.TransportError:
            time.sleep(0.5)
    raise RuntimeError(f"API on {port} did not start; see {log}")


def stream_events(client: httpx.Client, url: str, headers: dict[str, str], body: dict[str, str]):
    with client.stream("POST", url, headers=headers, json=body, timeout=30) as response:
        names = [line[7:] for line in response.iter_lines() if line.startswith("event: ")]
        return response, names


# --- checks -------------------------------------------------------------------------


def proxy_and_data_rights() -> None:
    client = httpx.Client(base_url=PROXY, timeout=30)
    alice, bob = user("alice"), user("bob")
    ta, tb = token(alice), token(bob)

    pre = client.options(
        "/v1/agent/stream",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization, content-type",
        },
    )
    check(
        "CORS preflight for /v1/agent/stream from the allowed origin (via nginx)",
        pre.status_code == 200 and pre.headers.get("access-control-allow-origin") == ORIGIN,
        f"{pre.status_code}, allow-origin={pre.headers.get('access-control-allow-origin')}",
    )
    bad = client.options(
        "/v1/agent/stream",
        headers={"Origin": "https://evil.example.com", "Access-Control-Request-Method": "POST"},
    )
    check(
        "CORS preflight from a disallowed origin",
        bad.status_code == 400 and "access-control-allow-origin" not in bad.headers,
        f"{bad.status_code}, no allow-origin",
    )

    anon = client.post("/v1/agent/invoke", json=prompt("anon"))
    check(
        "invoke without a token (via nginx)",
        anon.status_code == 401 and anon.headers.get("www-authenticate", "").startswith("Bearer"),
        f"{anon.status_code} {anon.json()} WWW-Authenticate={anon.headers.get('www-authenticate')}",
    )

    first = client.post(
        "/v1/agent/invoke", headers=auth(ta, Origin=ORIGIN), json=prompt("alice-one")
    )
    check(
        "authenticated invoke from the allowed origin (via nginx)",
        first.status_code == 200
        and first.headers.get("access-control-allow-origin") == ORIGIN
        and first.headers.get("cache-control") == "no-store",
        f"{first.status_code}, allow-origin={first.headers.get('access-control-allow-origin')}, "
        f"cache-control={first.headers.get('cache-control')}",
    )
    alice_thread = first.json()["thread_id"]

    started = time.monotonic()
    response, names = stream_events(
        client, "/v1/agent/stream", auth(ta, Origin=ORIGIN), prompt("alice-two")
    )
    check(
        "authenticated stream (via nginx, OPERATIONS.md location block)",
        response.status_code == 200
        and names[0] == "run_started"
        and names[-2:] == ["final", "done"]
        and "x-accel-buffering" not in response.headers,
        f"{response.status_code}, {Counter(names)}, {time.monotonic() - started:.2f}s, "
        f"content-type={response.headers.get('content-type')}, "
        f"cache-control={response.headers.get('cache-control')}, X-Accel-Buffering consumed by nginx",
    )

    bob_thread = client.post("/v1/agent/invoke", headers=auth(tb), json=prompt("bob-one")).json()[
        "thread_id"
    ]

    forbidden = client.post(
        "/v1/agent/invoke",
        headers=auth(token(alice, scope="threads:read")),
        json=prompt("no-scope"),
    )
    check(
        "token without agent:invoke",
        forbidden.status_code == 403
        and "insufficient_scope" in forbidden.headers.get("www-authenticate", ""),
        f"{forbidden.status_code} {forbidden.json()} {forbidden.headers.get('www-authenticate')}",
    )

    # Data rights on Postgres.
    listed = client.get("/v1/me/threads", headers=auth(ta)).json()
    check("Postgres: alice lists her threads", listed["total"] == 2, f"total={listed['total']}")
    bob_listed = client.get("/v1/me/threads", headers=auth(tb)).json()
    check(
        "Postgres: bob lists only his thread",
        [t["thread_id"] for t in bob_listed["threads"]] == [bob_thread],
        f"total={bob_listed['total']}",
    )
    cross = [
        client.get(f"/v1/threads/{alice_thread}/messages", headers=auth(tb)).status_code,
        client.delete(f"/v1/threads/{alice_thread}", headers=auth(tb)).status_code,
        client.post(
            "/v1/agent/invoke",
            headers=auth(tb),
            json={**prompt("bob-steal"), "thread_id": alice_thread},
        ).status_code,
    ]
    check(
        "Postgres: bob reads, deletes or continues alice's thread", cross == [404, 404, 404], cross
    )
    export = client.get("/v1/me/export", headers=auth(ta)).json()
    exported = json.dumps(export)
    check(
        "Postgres: alice exports her turns only",
        export["total_threads"] == 2
        and f"alice-one-{RUN}" in exported
        and "bob-one" not in exported,
        f"total_threads={export['total_threads']}, {len(exported)} bytes",
    )
    bob_export = json.dumps(client.get("/v1/me/export", headers=auth(tb)).json())
    check(
        "Postgres: bob's export has nothing of alice's",
        "alice-" not in bob_export,
        "no alice content",
    )
    erased = client.delete("/v1/me/threads", headers=auth(ta)).json()
    after = client.get("/v1/me/threads", headers=auth(ta)).json()["total"]
    bob_after = client.get("/v1/me/threads", headers=auth(tb)).json()["total"]
    check(
        "Postgres: alice erases all; bob is untouched",
        erased == {"erased_count": 2, "skipped_busy_count": 0} and after == 0 and bob_after == 1,
        f"{erased}, alice now {after}, bob {bob_after}",
    )
    client.delete("/v1/me/threads", headers=auth(tb))


def jwks_rotation_and_outage() -> None:
    client = httpx.Client(base_url=PROXY, timeout=30)
    carol = user("carol")
    k1_token = token(carol, kid="k1")
    check(
        "k1 token before rotation",
        client.get("/v1/me/threads", headers=auth(k1_token)).status_code == 200,
        200,
    )

    published.add("k2")
    current["kid"] = "k2"
    k2_token = token(carol, kid="k2")
    published_at = time.monotonic()
    first = client.get("/v1/me/threads", headers=auth(k2_token)).status_code
    waited = None
    while time.monotonic() - published_at < 45:
        if client.get("/v1/me/threads", headers=auth(k2_token)).status_code == 200:
            waited = time.monotonic() - published_at
            break
        time.sleep(1)
    check(
        "key rotation: a token from newly published k2 is accepted without a restart",
        waited is not None,
        f"first attempt {first}; accepted after {waited:.1f}s" if waited else f"first {first}; not accepted in 45s",
    )

    published.discard("k1")
    time.sleep(2.5)  # APP_AUTH_JWKS_CACHE_SECONDS=2
    retired = client.get("/v1/me/threads", headers=auth(token(carol, kid="k1")))
    check(
        "key rotation: k1 tokens are rejected once k1 leaves the JWKS and the cache expires",
        retired.status_code == 401,
        f"{retired.status_code} {retired.json()}",
    )

    jwks_down()
    time.sleep(2.5)
    outage = client.get("/v1/me/threads", headers=auth(k2_token))
    ready = client.get("/health/ready")
    check(
        "IdP/JWKS outage: valid token fails closed",
        outage.status_code == 503 and outage.json() == {"detail": "authentication_unavailable"},
        f"{outage.status_code} {outage.json()}",
    )
    check(
        "IdP/JWKS outage: readiness",
        ready.status_code == 503,
        f"{ready.status_code} {ready.json()}",
    )
    invalid = client.get("/v1/me/threads", headers=auth("not.a.token"))
    check(
        "IdP/JWKS outage: a malformed token is still 401 (no fetch needed)",
        invalid.status_code == 401,
        invalid.status_code,
    )

    jwks_up()
    recovered = client.get("/v1/me/threads", headers=auth(k2_token)).status_code
    ready_after = client.get("/health/ready").status_code
    check(
        "IdP recovery: requests and readiness recover",
        (recovered, ready_after) == (200, 200),
        f"request {recovered}, ready {ready_after}",
    )


def rate_limits() -> None:
    url = start_api(
        8001,
        "api-ratelimit.log",
        APP_RATE_LIMIT_ENABLED="true",
        APP_RATE_LIMIT_BURST="3",
        APP_RATE_LIMIT_REQUESTS_PER_WINDOW="1",
        APP_RATE_LIMIT_WINDOW_SECONDS="3600",
    )
    client = httpx.Client(base_url=url, timeout=30)
    dave, erin = token(user("dave")), token(user("erin"))
    codes = [client.get("/v1/me/threads", headers=auth(dave)).status_code for _ in range(4)]
    limited = client.get("/v1/me/threads", headers=auth(dave))
    check(
        "per-principal rate limit (burst 3)",
        codes == [200, 200, 200, 429] and limited.headers.get("retry-after") is not None,
        f"{codes}, then {limited.status_code} {limited.json()} Retry-After={limited.headers.get('retry-after')}",
    )
    other = client.get("/v1/me/threads", headers=auth(erin)).status_code
    check("another principal is unaffected", other == 200, other)
    bad = [
        client.get("/v1/me/threads", headers=auth("bad.token.value")).status_code for _ in range(4)
    ]
    check("failed authentication is limited per IP", bad == [401, 401, 401, 429], bad)


def run_cap_and_budget() -> None:
    url = start_api(
        8002,
        "api-limits.log",
        GATE_MODEL_DELAY="2",
        GATE_MODEL_TOKENS="400",
        APP_MAX_CONCURRENT_RUNS_PER_USER="2",
        APP_USER_TOKEN_BUDGET="1000",
    )
    fred, gina = token(user("fred")), token(user("gina"))
    results_box: list[int] = []

    def run(value: str) -> None:
        response = httpx.post(
            f"{url}/v1/agent/invoke", headers=auth(value), json=prompt("slow"), timeout=30
        )
        results_box.append(response.status_code)

    workers = [threading.Thread(target=run, args=(fred,)) for _ in range(2)]
    for worker in workers:
        worker.start()
    time.sleep(0.8)
    third = httpx.post(
        f"{url}/v1/agent/invoke", headers=auth(fred), json=prompt("third"), timeout=30
    )
    other = httpx.post(
        f"{url}/v1/agent/invoke", headers=auth(gina), json=prompt("gina"), timeout=30
    )
    for worker in workers:
        worker.join()
    check(
        "per-principal concurrent-run cap (2)",
        third.status_code == 429
        and third.json() == {"detail": "too_many_concurrent_runs"}
        and third.headers.get("retry-after") is not None
        and sorted(results_box) == [200, 200],
        f"two runs {sorted(results_box)}, third {third.status_code} {third.json()} "
        f"Retry-After={third.headers.get('retry-after')}",
    )
    check("another principal runs during the cap", other.status_code == 200, other.status_code)

    codes = []
    for _ in range(4):
        response = httpx.post(
            f"{url}/v1/agent/invoke", headers=auth(fred), json=prompt("budget"), timeout=30
        )
        codes.append(response.status_code)
        if response.status_code == 429:
            break
    check(
        "per-principal token budget (1000 tokens, 400 per model call)",
        codes[-1] == 429
        and response.json() == {"detail": "quota_exceeded"}
        and response.headers.get("retry-after") is not None,
        f"after the 2 capped runs: {codes}, {response.json()} Retry-After={response.headers.get('retry-after')}",
    )


def refuse_to_start() -> None:
    def boot(**env: str) -> tuple[int, str]:
        full = {
            k: v for k, v in os.environ.items() if not k.startswith("APP_") and "OPENAI" not in k
        }
        full.update(env)
        done = subprocess.run(
            ["uv", "run", "--project", REPO, "python", "-c", "import neuron_agent.api.main"],
            cwd=GATE,
            env=full,
            capture_output=True,
            text=True,
        )
        message = next((line for line in done.stderr.splitlines() if "Value error" in line), "")
        return done.returncode, message.strip()

    jwt_ok = {
        "APP_AUTH_MODE": "jwt",
        "APP_AUTH_ISSUER": ISSUER,
        "APP_AUTH_AUDIENCE": AUDIENCE,
        "APP_AUTH_JWKS_URL": "https://idp.gate.test/jwks.json",
        "APP_IDENTITY_HASH_KEY": "g" * 40,
        "OPENAI_API_KEY": "sk-gate",
        "APP_CHECKPOINTER": "none",
    }
    cases = {
        "production, no auth settings": {"APP_ENV": "production", "OPENAI_API_KEY": "sk-gate"},
        "staging, no auth settings": {"APP_ENV": "staging", "OPENAI_API_KEY": "sk-gate"},
        "production, APP_AUTH_MODE=none": {
            "APP_ENV": "production",
            "APP_AUTH_MODE": "none",
            "OPENAI_API_KEY": "sk-gate",
        },
        "production, jwt without APP_IDENTITY_HASH_KEY": {
            **jwt_ok,
            "APP_ENV": "production",
            "APP_IDENTITY_HASH_KEY": "",
        },
        "production, http JWKS URL": {
            **jwt_ok,
            "APP_ENV": "production",
            "APP_AUTH_JWKS_URL": "http://idp.gate.test/jwks.json",
        },
        "staging, jwt without APP_AUTH_AUDIENCE": {
            **jwt_ok,
            "APP_ENV": "staging",
            "APP_AUTH_AUDIENCE": "",
        },
    }
    for name, env in cases.items():
        code, message = boot(**env)
        check(f"refuses to start: {name}", code != 0 and message != "", message or f"exit {code}")
    code, _ = boot(**jwt_ok, APP_ENV="production")
    check("starts: production with complete jwt settings (control)", code == 0, f"exit {code}")


def audit_review() -> None:
    lines: list[str] = []
    for log in ("api.log", "api-ratelimit.log", "api-limits.log"):
        lines += (GATE / log).read_text(errors="replace").splitlines()
    records = []
    for line in lines:
        try:
            records.append(json.loads(line))
        except ValueError:
            continue
    audits = [r for r in records if r.get("audit") is True]
    events = Counter(r["event"] for r in audits)
    reasons = Counter(f"{r['event']}:{r['reason']}" for r in audits if r.get("reason"))
    print("audit events:", dict(events))
    print("audit reasons:", dict(reasons))
    required = {
        "auth_failed",
        "auth_succeeded",
        "authorization_denied",
        "thread_created",
        "user_data_exported",
        "user_data_erased",
        "limit_exceeded",
    }
    check(
        "audit: required events present",
        required <= set(events),
        sorted(required - set(events)) or "all present",
    )
    needed_reasons = {
        "auth_failed:missing_token",
        "auth_failed:jwks_unavailable",
        "auth_failed:unknown_signing_key",
        "authorization_denied:insufficient_scope",
        "authorization_denied:thread_not_found",
        "limit_exceeded:request_rate",
        "limit_exceeded:authentication_attempts",
        "limit_exceeded:concurrent_runs",
        "limit_exceeded:token_budget",
    }
    check(
        "audit: reasons observed",
        needed_reasons <= set(reasons),
        sorted(needed_reasons - set(reasons)) or "all present",
    )
    text = "\n".join(lines)
    leaked = sorted(s for s in secrets_seen if s in text)
    check(
        f"logs: none of {len(secrets_seen)} tokens, token signatures, subjects or prompts appear "
        f"in {len(lines)} log lines",
        not leaked,
        # Only a count: a leaked token must not be printed by the check that found it.
        f"{len(leaked)} found" if leaked else "none found",
    )
    ip_in_audit = [r["event"] for r in audits if "127.0.0.1" in json.dumps(r)]
    check(
        f"audit: no raw client IP in {len(audits)} audit records",
        not ip_in_audit,
        ip_in_audit[:3] or "none",
    )
    schema = {
        "audit",
        "outcome",
        "actor",
        "issuer_id",
        "action",
        "resource_type",
        "resource_id",
        "request_id",
        "run_id",
        "reason",
        "count",
        "timestamp",
        "event",
        "level",
        "logger",
        "service",
        "version",
        "environment",
        "thread_id",
    }
    extra = sorted({key for r in audits for key in r} - schema)
    check("audit: records carry only the documented fields", not extra, extra or "fixed schema")


def main() -> int:
    jwks_up()
    try:
        start_api(8000, "api.log")
        subprocess.run(["nginx", "-c", str(GATE / "nginx.conf"), "-p", str(GATE)], check=True)
        proxy_and_data_rights()
        jwks_rotation_and_outage()
        rate_limits()
        run_cap_and_budget()
        refuse_to_start()
        audit_review()
    finally:
        subprocess.run(["nginx", "-c", str(GATE / "nginx.conf"), "-p", str(GATE), "-s", "stop"])
        for process in servers:
            process.terminate()
    failed = [name for name, _, ok in results if not ok]
    (GATE / "results.json").write_text(json.dumps(results, indent=1))
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
