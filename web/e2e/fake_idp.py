"""A stand-in OpenID provider for the browser tests: PKCE code flow, one user per sign-in.

It speaks just enough of the protocol for the web app and the API (discovery, authorization
form, token endpoint, JWKS, end-session) and signs tokens the API verifies over its normal JWT
path. The real Keycloak path is covered by `tests/integration/test_keycloak.py`. Local use only.
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import secrets
import sys
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import jwt
from cryptography.hazmat.primitives.asymmetric import ec

PORT = 8180
REALM = "/realms/neuron"
ISSUER = f"http://localhost:{PORT}{REALM}"
OIDC = f"{REALM}/protocol/openid-connect"
CLIENT_ID = "neuron-web"
AUDIENCE = "neuron-api"
APP_ORIGIN = "http://localhost:5173"
KID = "browser-e2e"
PERMISSIONS = (
    "agent:approve agent:invoke feedback:write memories:read memories:write threads:delete "
    "threads:read threads:write tools:calculator tools:forget tools:recall tools:remember"
)

KEY = ec.generate_private_key(ec.SECP256R1())
JWK = {**json.loads(jwt.algorithms.ECAlgorithm.to_jwk(KEY.public_key())), "kid": KID}
JWK.update(alg="ES256", use="sig")
CODES: dict[str, dict[str, str]] = {}


def _token(claims: dict[str, object], headers: dict[str, str] | None = None) -> str:
    now = int(time.time())
    body = {"iss": ISSUER, "iat": now, "nbf": now, "exp": now + 1800, **claims}
    return jwt.encode(body, KEY, algorithm="ES256", headers={"kid": KID, **(headers or {})})


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:
        return

    def _send(self, status: int, body: bytes, content_type: str, **headers: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", APP_ORIGIN)
        for name, value in headers.items():
            self.send_header(name.replace("_", "-"), value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: object, status: int = 200) -> None:
        self._send(status, json.dumps(payload).encode(), "application/json")

    def _redirect(self, location: str) -> None:
        self._send(302, b"", "text/plain", Location=location)

    def do_OPTIONS(self) -> None:  # noqa: N802 - http.server's naming
        self._send(
            204,
            b"",
            "text/plain",
            Access_Control_Allow_Headers="content-type",
            Access_Control_Allow_Methods="GET, POST",
        )

    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path == f"{REALM}/.well-known/openid-configuration":
            self._json(
                {
                    "issuer": ISSUER,
                    "authorization_endpoint": f"http://localhost:{PORT}{OIDC}/auth",
                    "token_endpoint": f"http://localhost:{PORT}{OIDC}/token",
                    "end_session_endpoint": f"http://localhost:{PORT}{OIDC}/logout",
                    "jwks_uri": f"http://localhost:{PORT}{OIDC}/certs",
                }
            )
        elif url.path == f"{OIDC}/certs":
            self._json({"keys": [JWK]})
        elif url.path == f"{OIDC}/auth":
            self._authorize(query)
        elif url.path == f"{OIDC}/logout":
            self._redirect(query.get("post_logout_redirect_uri", APP_ORIGIN + "/"))
        else:
            self._send(404, b"not found", "text/plain")

    def _authorize(self, query: dict[str, str]) -> None:
        if query.get("client_id") != CLIENT_ID or query.get("redirect_uri") != APP_ORIGIN + "/":
            self._send(400, b"Invalid parameter: redirect_uri", "text/plain")
            return
        if query.get("prompt") == "none":  # silent renew: this provider keeps no session
            params = urlencode({"error": "login_required", "state": query.get("state", "")})
            self._redirect(f"{query['redirect_uri']}?{params}")
            return
        fields = "".join(
            f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(v)}">'
            for k, v in query.items()
        )
        page = (
            "<!doctype html><title>Sign in</title><form method=post action=''>"
            f"{fields}<label>Username <input id=username name=username></label>"
            "<button id=login type=submit>Log in</button></form>"
        )
        self._send(200, page.encode(), "text/html")

    def do_POST(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        form = {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode()).items()}
        if url.path == f"{OIDC}/auth":
            code = secrets.token_urlsafe(24)
            CODES[code] = {
                "user": form.get("username", "") or "anonymous",
                "nonce": form.get("nonce", ""),
                "challenge": form.get("code_challenge", ""),
            }
            params = urlencode({"code": code, "state": form.get("state", ""), "iss": ISSUER})
            self._redirect(f"{form['redirect_uri']}?{params}")
        elif url.path == f"{OIDC}/token":
            self._exchange(form)
        else:
            self._send(404, b"not found", "text/plain")

    def _exchange(self, form: dict[str, str]) -> None:
        grant = CODES.pop(form.get("code", ""), None)
        verifier = form.get("code_verifier", "")
        digest = hashlib.sha256(verifier.encode()).digest()
        challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
        if grant is None or grant["challenge"] != challenge:
            self._json({"error": "invalid_grant"}, 400)
            return
        user = grant["user"]
        access = _token(
            {"aud": AUDIENCE, "sub": user, "scope": PERMISSIONS, "jti": str(uuid.uuid4())},
            {"typ": "at+jwt"},
        )
        identity = _token(
            {"aud": CLIENT_ID, "sub": user, "nonce": grant["nonce"], "preferred_username": user}
        )
        self._json(
            {
                "access_token": access,
                "id_token": identity,
                "token_type": "Bearer",
                "expires_in": 1800,
            }
        )


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"fake_idp: {ISSUER}", file=sys.stderr, flush=True)
    server.serve_forever()
