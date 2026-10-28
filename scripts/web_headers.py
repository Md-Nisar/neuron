# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Reference security headers for whoever hosts `web/dist` (ADR 0010, decision 7).

The web application is static files served from its own origin; the API image does not serve
it. The content security policy depends on two origins only: the API (where the bearer token
goes) and the identity provider (the token and discovery endpoints, and the silent-renew frame).

    python scripts/web_headers.py --api-origin https://api.example.com \\
        --issuer https://id.example.com/realms/neuron --format nginx

Formats: `json`, `nginx` (`add_header` lines) and `headers` (the `_headers` file read by
Netlify and Cloudflare Pages). `--development` is for the local Keycloak and API on loopback
(plain HTTP, no HSTS, no `upgrade-insecure-requests`).

The two origins go into a header, so they are checked strictly: a bare `scheme://host[:port]`
in ASCII, HTTPS unless loopback in development. A value that could add a directive (`;`, `,`,
spaces, quotes), widen the policy (`*`) or smuggle a path is refused, never escaped.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import sys
from urllib.parse import urlsplit

_LOOPBACK = {"localhost", "127.0.0.1", "[::1]"}
_HOST = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*$")


class HeaderConfigError(ValueError):
    """An origin that cannot be put safely into a header."""


def origin_of(value: str, *, development: bool = False, allow_path: bool = False) -> str:
    """The `scheme://host[:port]` of `value`, or raise if it is not safe to use in a policy.

    A path is accepted only for the issuer (its URL ends in `/realms/...`); the API setting must
    be a bare origin, as the web application itself requires.
    """
    if not value.isascii() or any(ch in value for ch in " \t\r\n;,\"'*\\<>"):
        raise HeaderConfigError(f"not a plain origin: {value!r}")
    parts = urlsplit(value)
    if parts.scheme not in {"https", "http"} or not parts.hostname:
        raise HeaderConfigError(f"not an http(s) origin: {value!r}")
    if parts.username is not None or parts.password is not None or parts.query or parts.fragment:
        raise HeaderConfigError(f"origin carries credentials, a query or a fragment: {value!r}")
    if parts.path not in ("", "/") and not allow_path:
        raise HeaderConfigError(f"expected an origin without a path: {value!r}")
    host = parts.hostname
    bracketed = f"[{host}]" if ":" in host else host
    loopback = bracketed in _LOOPBACK
    if loopback is False:
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if not _HOST.fullmatch(host):
                raise HeaderConfigError(f"not a valid host name: {value!r}") from None
    if parts.scheme == "http" and not (development and loopback):
        raise HeaderConfigError(f"plain HTTP is allowed only on loopback in development: {value!r}")
    try:
        port = parts.port
    except ValueError:
        raise HeaderConfigError(f"invalid port: {value!r}") from None
    return f"{parts.scheme}://{bracketed}" + (f":{port}" if port is not None else "")


def content_security_policy(*, api_origin: str, issuer: str, development: bool = False) -> str:
    """The CSP: scripts, styles, images and fonts from this origin only, no inline anything."""
    api = origin_of(api_origin, development=development)
    idp = origin_of(issuer, development=development, allow_path=True)
    directives = [
        "default-src 'none'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self'",
        "font-src 'self'",
        f"connect-src {api} {idp}" if api != idp else f"connect-src {api}",
        f"frame-src {idp}",
        # 'self', not 'none': silent renew loads this app in a frame of itself (web/README.md).
        "frame-ancestors 'self'",
        "base-uri 'none'",
        "form-action 'none'",
        "object-src 'none'",
        "worker-src 'none'",
    ]
    if not development:
        directives.append("upgrade-insecure-requests")
    return "; ".join(directives)


def security_headers(*, api_origin: str, issuer: str, development: bool = False) -> dict[str, str]:
    """Headers for every response, including the HTML."""
    headers = {
        "Content-Security-Policy": content_security_policy(
            api_origin=api_origin, issuer=issuer, development=development
        ),
        # The sign-in callback URL carries a one-time code: never send it in a Referer.
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "SAMEORIGIN",
        "Cross-Origin-Opener-Policy": "same-origin",
        "Cross-Origin-Resource-Policy": "same-origin",
        "Permissions-Policy": (
            "accelerometer=(), camera=(), clipboard-read=(), clipboard-write=(), "
            "geolocation=(), gyroscope=(), magnetometer=(), microphone=(), payment=(), usb=()"
        ),
        "X-Permitted-Cross-Domain-Policies": "none",
    }
    if not development:
        headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return headers


# Cache rules by path: the HTML must be revalidated (it names the hashed files); the hashed
# files never change.
CACHE_RULES: dict[str, str] = {
    "/index.html": "no-cache",
    "/assets/*": "public, max-age=31536000, immutable",
}


def render_json(headers: dict[str, str]) -> str:
    return json.dumps({"headers": headers, "cache": CACHE_RULES}, indent=2) + "\n"


def render_nginx(headers: dict[str, str]) -> str:
    """`add_header` lines for every location.

    nginx does not inherit `add_header` into a block that has its own `add_header`, so each
    location repeats the whole set: a cache rule must not strip the CSP from the HTML.
    """

    def block(opener: str, cache: str | None) -> list[str]:
        lines = [opener]
        lines += [f'    add_header {name} "{value}" always;' for name, value in headers.items()]
        if cache is not None:
            lines.append(f'    add_header Cache-Control "{cache}" always;')
        return [*lines, "}"]

    lines = ["# Reference headers for web/dist (scripts/web_headers.py)."]
    lines += block("location = /index.html {", CACHE_RULES["/index.html"])
    lines += block("location /assets/ {", CACHE_RULES["/assets/*"])
    lines += block("location / {", None)
    return "\n".join(lines) + "\n"


def render_headers_file(headers: dict[str, str]) -> str:
    lines = ["/*"] + [f"  {name}: {value}" for name, value in headers.items()]
    lines += ["/index.html", f"  Cache-Control: {CACHE_RULES['/index.html']}"]
    lines += ["/assets/*", f"  Cache-Control: {CACHE_RULES['/assets/*']}"]
    return "\n".join(lines) + "\n"


_RENDERERS = {"json": render_json, "nginx": render_nginx, "headers": render_headers_file}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--api-origin", required=True, help="the API origin, e.g. https://api.example.com"
    )
    parser.add_argument("--issuer", required=True, help="the OIDC issuer URL (its origin is used)")
    parser.add_argument("--format", choices=sorted(_RENDERERS), default="json")
    parser.add_argument("--development", action="store_true", help="loopback HTTP, no HSTS")
    args = parser.parse_args(argv)
    try:
        headers = security_headers(
            api_origin=args.api_origin, issuer=args.issuer, development=args.development
        )
    except HeaderConfigError as exc:
        print(f"web_headers: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write(_RENDERERS[args.format](headers))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
