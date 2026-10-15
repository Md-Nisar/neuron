"""Mint local development access tokens without an identity provider (#62).

Development only: every command refuses to run unless `APP_ENV=development`. The key
pair and JWKS live in `.dev/` (git-ignored). The API fetches the JWKS over plain HTTP from
a loopback-only server, which settings allow only in development, so local runs use the
same JWKS path as production.

    uv run python scripts/dev_token.py setup >> .env   # once: key pair, JWKS, settings
    uv run python scripts/dev_token.py serve           # keep running: serves the JWKS
    uv run python scripts/dev_token.py                 # print a token

`make dev-auth`, `make dev-jwks` and `make dev-token` run the same commands.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import sys
import uuid
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from pydantic import ValidationError

from neuron_agent.config.settings import Settings
from neuron_agent.security.authorization import DEV_PERMISSIONS

DEV_DIR = Path(__file__).resolve().parent.parent / ".dev"
DEV_ISSUER = "http://localhost/neuron-dev"
DEV_AUDIENCE = "neuron-api"
DEV_JWKS_PORT = 8765
_ALGORITHM = "ES256"


class DevTokenError(Exception):
    """A refusal or misconfiguration, reported without a traceback."""


def ensure_keys(directory: Path) -> tuple[ec.EllipticCurvePrivateKey, str]:
    """Create the signing key once, (re)write the public JWKS, and return the key and kid."""
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    key_path = directory / "jwt-private.pem"
    if not key_path.exists():
        pem = ec.generate_private_key(ec.SECP256R1()).private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        try:
            descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass  # another run created it first; use that one
        else:
            with os.fdopen(descriptor, "wb") as key_file:
                key_file.write(pem)
    try:
        key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    except ValueError as exc:
        raise DevTokenError(f"{key_path} is unreadable; delete it and rerun setup") from exc
    if not isinstance(key, ec.EllipticCurvePrivateKey):
        raise DevTokenError(f"{key_path} is not an EC private key; delete it and rerun setup")
    public_jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(key.public_key()))
    # RFC 7638 thumbprint: SHA-256 over the required members in lexicographic order.
    required = {name: public_jwk[name] for name in ("crv", "kty", "x", "y")}
    digest = hashlib.sha256(json.dumps(required, separators=(",", ":")).encode()).digest()
    kid = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    jwks = {"keys": [{**public_jwk, "kid": kid, "alg": _ALGORITHM, "use": "sig"}]}
    jwks_path(directory).write_text(json.dumps(jwks, indent=2) + "\n")
    return key, kid


def jwks_path(directory: Path) -> Path:
    return directory / "jwks.json"


def env_block() -> str:
    """The `.env` lines that make a development API trust tokens from this script."""
    return "\n".join(
        [
            "",
            "# Local development tokens from scripts/dev_token.py. Development only.",
            "APP_AUTH_MODE=jwt",
            f"APP_AUTH_ISSUER={DEV_ISSUER}",
            f"APP_AUTH_AUDIENCE={DEV_AUDIENCE}",
            f"APP_AUTH_JWKS_URL=http://127.0.0.1:{DEV_JWKS_PORT}/jwks.json",
            f"APP_IDENTITY_HASH_KEY={secrets.token_urlsafe(32)}",
            "",
        ]
    )


def mint(
    settings: Settings,
    directory: Path,
    *,
    subject: str,
    scopes: str,
    ttl: timedelta,
) -> str:
    """Sign an RFC 9068-shaped access token the configured development API accepts."""
    if settings.auth_mode != "jwt" or settings.auth_issuer != DEV_ISSUER:
        raise DevTokenError(
            "the API isn't configured for development tokens; run "
            "`uv run python scripts/dev_token.py setup >> .env` (or `make dev-auth >> .env`)"
        )
    if _ALGORITHM not in settings.auth_algorithms:
        raise DevTokenError(f"APP_AUTH_ALGORITHMS must include {_ALGORITHM}")
    key, kid = ensure_keys(directory)
    now = datetime.now(UTC)
    claims = {
        "iss": settings.auth_issuer,
        "aud": settings.auth_audience,
        "sub": subject,
        "scope": scopes,
        "iat": now,
        "nbf": now,
        "exp": now + ttl,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(claims, key, algorithm=_ALGORITHM, headers={"kid": kid, "typ": "at+jwt"})


class _JwksServer(ThreadingHTTPServer):
    # On Windows, SO_REUSEADDR lets a second server bind a port that is already listening.
    allow_reuse_address = os.name != "nt"


def jwks_server(directory: Path, port: int) -> ThreadingHTTPServer:
    """A loopback-only server that answers `GET /jwks.json` and nothing else."""
    body = jwks_path(directory).read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - http.server's naming
            if self.path != "/jwks.json":
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return _JwksServer(("127.0.0.1", port), Handler)


def _development_settings() -> Settings:
    try:
        settings = Settings()
    except ValidationError as exc:
        raise DevTokenError(f"settings are invalid: {exc.errors()[0]['msg']}") from exc
    if settings.env != "development":
        raise DevTokenError(
            f"development tokens are refused when APP_ENV={settings.env}; "
            "use your identity provider outside local development"
        )
    return settings


def main(argv: list[str] | None = None, *, directory: Path = DEV_DIR) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", nargs="?", choices=["setup", "serve", "token"], default="token")
    parser.add_argument("--sub", default="dev-user", help="token subject (default: dev-user)")
    parser.add_argument(
        "--scope",
        default=" ".join(sorted(DEV_PERMISSIONS)),
        help="space-delimited scopes (default: every permission)",
    )
    parser.add_argument(
        "--ttl-minutes", type=int, default=60, choices=range(1, 1441), metavar="1-1440"
    )
    args = parser.parse_args(argv)
    try:
        settings = _development_settings()
        if args.command == "setup":
            ensure_keys(directory)
            print(env_block())
        elif args.command == "serve":
            ensure_keys(directory)
            try:
                server = jwks_server(directory, DEV_JWKS_PORT)
            except OSError as exc:
                raise DevTokenError(
                    f"can't listen on 127.0.0.1:{DEV_JWKS_PORT} ({exc.strerror}); "
                    "is another dev-jwks already running?"
                ) from exc
            print(
                f"dev_token: serving http://127.0.0.1:{DEV_JWKS_PORT}/jwks.json (Ctrl+C stops)",
                file=sys.stderr,
            )
            with server:
                try:
                    server.serve_forever()
                except KeyboardInterrupt:
                    pass
        else:
            ttl = timedelta(minutes=args.ttl_minutes)
            print(mint(settings, directory, subject=args.sub, scopes=args.scope, ttl=ttl))
    except DevTokenError as exc:
        print(f"dev_token: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
