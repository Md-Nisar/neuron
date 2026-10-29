"""A real API process for end-to-end flows: uvicorn, the fake model, signed bearer tokens.

The server runs as a subprocess with in-memory persistence and a loopback JWKS, the same
JWT path production uses. Nothing here reaches a provider or the network beyond loopback.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

ISSUER = "http://localhost/neuron-e2e"
AUDIENCE = "neuron-api"
KID = "e2e-key"
PERMISSIONS = (
    "agent:approve agent:invoke feedback:write memories:read memories:write threads:delete "
    "threads:read threads:write tools:calculator tools:forget tools:recall tools:remember"
)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class Api:
    """The running server and a token factory for its issuer."""

    def __init__(self, base_url: str, key: ec.EllipticCurvePrivateKey) -> None:
        self.base_url = base_url
        self._key = key

    def token(self, subject: str, scope: str = PERMISSIONS) -> str:
        now = datetime.now(UTC)
        claims = {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": subject,
            "scope": scope,
            "iat": now,
            "nbf": now,
            "exp": now + timedelta(minutes=30),
            "jti": str(uuid.uuid4()),
        }
        return jwt.encode(
            claims, self._key, algorithm="ES256", headers={"kid": KID, "typ": "at+jwt"}
        )

    def client(self, subject: str, scope: str = PERMISSIONS) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {self.token(subject, scope)}"},
            timeout=30,
        )


def stream_events(response: httpx.Response) -> list[tuple[str, dict[str, object]]]:
    """Parse a server-sent-event body into (event, data) pairs, skipping heartbeats."""
    events: list[tuple[str, dict[str, object]]] = []
    name = ""
    for line in response.text.splitlines():
        if line.startswith("event:"):
            name = line.partition(":")[2].strip()
        elif line.startswith("data:") and name:
            events.append((name, json.loads(line.partition(":")[2])))
            name = ""
    return events


@pytest.fixture(scope="session")
def api(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Api]:
    key = ec.generate_private_key(ec.SECP256R1())
    public = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(key.public_key()))
    jwks = json.dumps({"keys": [{**public, "kid": KID, "alg": "ES256", "use": "sig"}]}).encode()

    class JwksHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - http.server's naming
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(jwks)))
            self.end_headers()
            self.wfile.write(jwks)

        def log_message(self, *args: object) -> None:
            return

    jwks_server = ThreadingHTTPServer(("127.0.0.1", 0), JwksHandler)
    threading.Thread(target=jwks_server.serve_forever, daemon=True).start()

    port = _free_port()
    env = {
        **os.environ,
        "APP_ENV": "development",
        "APP_DEFAULT_MODEL": "openai:gpt-5.4-mini",
        "APP_OPENAI_API_KEY": "",
        "OPENAI_API_KEY": "",
        "APP_AUTH_MODE": "jwt",
        "APP_AUTH_ISSUER": ISSUER,
        "APP_AUTH_AUDIENCE": AUDIENCE,
        "APP_AUTH_ALGORITHMS": '["ES256"]',
        "APP_AUTH_JWKS_URL": f"http://127.0.0.1:{jwks_server.server_address[1]}/jwks.json",
        "APP_IDENTITY_HASH_KEY": "e2e-identity-hash-key-not-a-secret-0001",
        "APP_CHECKPOINTER": "memory",
        "APP_MEMORY_ENABLED": "true",
        "APP_OTEL_ENABLED": "false",
        "APP_ENABLE_LANGSMITH": "false",
        "APP_FAKE_MODEL_TTFT_MS": "1",
        "APP_RATE_LIMIT_ENABLED": "false",
        "APP_USER_TOKEN_BUDGET": "10000000",
        "APP_ALLOWED_HOSTS": '["localhost","127.0.0.1"]',
    }
    log = tmp_path_factory.mktemp("e2e") / "api.log"
    with log.open("wb") as sink:
        process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
            [
                sys.executable,
                "-m",
                "uvicorn",
                "neuron_agent.api.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "warning",
            ],
            env=env,
            stdout=sink,
            stderr=subprocess.STDOUT,
        )
        base_url = f"http://127.0.0.1:{port}"
        try:
            deadline = time.monotonic() + 60
            while True:
                if process.poll() is not None:
                    pytest.fail(f"the API exited early:\n{log.read_text(errors='replace')[-2000:]}")
                try:
                    if httpx.get(f"{base_url}/health/live", timeout=2).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if time.monotonic() > deadline:
                    pytest.fail("the API did not become ready in 60 s")
                time.sleep(0.2)
            yield Api(base_url, key)
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
            jwks_server.shutdown()


@pytest.fixture
def user(api: Api) -> Callable[[str], httpx.Client]:
    """A client signed in as a fresh user, so tests never share threads or memories."""

    def make(prefix: str = "user") -> httpx.Client:
        return api.client(f"{prefix}-{uuid.uuid4().hex[:8]}")

    return make
