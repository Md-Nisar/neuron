"""HTTP surface hardening for browser and multi-user exposure (#60).

CORS, API docs exposure, response security headers, the Host check and the correlation ID,
through the real middleware stack with JWT authentication.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import pytest
import structlog.testing
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from pydantic import ValidationError
from tests.conftest import JwtApi, bearer

from neuron_agent.api import main as api_main
from neuron_agent.config.settings import Settings
from neuron_agent.security.rate_limiter import InMemoryTokenBucketRateLimiter

_APP_ORIGIN = "https://app.example.com"
_DOCS_PATHS = ["/docs", "/redoc", "/openapi.json"]


@pytest.fixture
def token(make_token: Callable[..., str]) -> dict[str, str]:
    return bearer(make_token())


def _assert_security_headers(response: Any) -> None:
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert (
        response.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"
    )
    assert "strict-transport-security" not in response.headers


# --- Settings ---------------------------------------------------------------------------


def test_wildcard_cors_origin_is_rejected_because_requests_carry_credentials() -> None:
    with pytest.raises(ValidationError, match="must not contain '\\*'"):
        Settings(env="test", cors_allowed_origins=["*"])
    with pytest.raises(ValidationError, match="must not contain '\\*'"):
        Settings(env="test", cors_allowed_origins=[_APP_ORIGIN, "*"])


@pytest.mark.parametrize(
    "origin",
    [
        "https://app.example.com/",  # browsers never send a trailing slash
        "https://app.example.com/path",
        "https://App.Example.com",  # matching is exact, browsers send lowercase
        "app.example.com",
        "null",  # sandboxed iframes and file:// pages
        "ftp://app.example.com",
    ],
)
def test_cors_origins_must_be_exact_browser_origins(origin: str) -> None:
    with pytest.raises(ValidationError, match="scheme://host"):
        Settings(env="test", cors_allowed_origins=[origin])


def test_cors_origins_accept_ports_and_ipv6() -> None:
    origins = ["http://localhost:5173", "https://app.example.com", "http://[::1]:3000"]
    assert Settings(env="test", cors_allowed_origins=origins).cors_allowed_origins == origins


@pytest.mark.parametrize(
    ("env", "exposed"),
    [("development", True), ("test", True), ("staging", False), ("production", False)],
)
def test_api_docs_are_hidden_outside_development_by_default(env: str, exposed: bool) -> None:
    settings = Settings.model_construct(env=env, expose_api_docs=None).validate_http_surface()
    assert settings.expose_api_docs is exposed


def test_api_docs_default_can_be_overridden() -> None:
    assert Settings(env="test", expose_api_docs=False).expose_api_docs is False


@pytest.mark.parametrize(
    "host", ["https://api.example.com", "api.example.com:443", "API.example.com", "[::1]", ""]
)
def test_allowed_hosts_must_be_matchable_hostnames(host: str) -> None:
    with pytest.raises(ValidationError, match="APP_ALLOWED_HOSTS"):
        Settings(env="test", allowed_hosts=[host])


def test_allowed_hosts_accept_names_and_subdomain_wildcards() -> None:
    hosts = ["api.example.com", "*.example.com", "10.0.0.7"]
    assert Settings(env="test", allowed_hosts=hosts).allowed_hosts == hosts


# --- CORS -------------------------------------------------------------------------------


def test_allowed_origin_can_read_responses(
    jwt_api_factory: Callable[..., JwtApi], token: dict[str, str]
) -> None:
    api = jwt_api_factory(cors_allowed_origins=[_APP_ORIGIN])
    response = api.client.get("/v1/me/threads", headers={**token, "Origin": _APP_ORIGIN})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == _APP_ORIGIN
    assert "access-control-allow-credentials" not in response.headers
    exposed = response.headers["access-control-expose-headers"].lower()
    assert "retry-after" in exposed
    assert "x-correlation-id" in exposed


def test_allowed_origin_can_read_error_responses(jwt_api_factory: Callable[..., JwtApi]) -> None:
    api = jwt_api_factory(cors_allowed_origins=[_APP_ORIGIN])
    response = api.client.get("/v1/me/threads", headers={"Origin": _APP_ORIGIN})

    assert response.status_code == 401
    assert response.headers["access-control-allow-origin"] == _APP_ORIGIN


@pytest.mark.parametrize("allowed", [[], [_APP_ORIGIN]])
def test_disallowed_origin_gets_no_cors_headers(
    jwt_api_factory: Callable[..., JwtApi], token: dict[str, str], allowed: list[str]
) -> None:
    api = jwt_api_factory(cors_allowed_origins=allowed)
    response = api.client.get(
        "/v1/me/threads", headers={**token, "Origin": "https://evil.example.com"}
    )

    # Starlette also sends its static Access-Control-Expose-Headers list, which browsers
    # ignore without an allow-origin grant.
    assert "access-control-allow-origin" not in response.headers
    assert "access-control-allow-credentials" not in response.headers


def test_stream_preflight_succeeds_for_an_allowed_origin(
    jwt_api_factory: Callable[..., JwtApi],
) -> None:
    api = jwt_api_factory(cors_allowed_origins=[_APP_ORIGIN])
    response = api.client.options(
        "/v1/agent/stream",
        headers={
            "Origin": _APP_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization, content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == _APP_ORIGIN
    assert "POST" in response.headers["access-control-allow-methods"]
    allowed_headers = response.headers["access-control-allow-headers"].lower()
    assert "authorization" in allowed_headers
    assert "content-type" in allowed_headers
    assert "access-control-allow-credentials" not in response.headers
    _assert_security_headers(response)


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://evil.example.com", "Access-Control-Request-Method": "POST"},
        {"Origin": _APP_ORIGIN, "Access-Control-Request-Method": "PUT"},
        {
            "Origin": _APP_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-user-id",
        },
    ],
)
def test_preflight_outside_the_policy_is_refused(
    jwt_api_factory: Callable[..., JwtApi], headers: dict[str, str]
) -> None:
    api = jwt_api_factory(cors_allowed_origins=[_APP_ORIGIN])
    response = api.client.options("/v1/agent/stream", headers=headers)

    assert response.status_code == 400


# --- API docs ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", _DOCS_PATHS)
def test_api_docs_are_not_found_in_production(
    jwt_api_factory: Callable[..., JwtApi], path: str
) -> None:
    api = jwt_api_factory(env="production", openai_api_key="sk-test")
    response = api.client.get(path)

    assert response.status_code == 404
    _assert_security_headers(response)


@pytest.mark.parametrize("path", _DOCS_PATHS)
def test_api_docs_gate_holds_behind_a_root_path(
    jwt_api_factory: Callable[..., JwtApi], path: str
) -> None:
    jwt_api_factory(env="production", openai_api_key="sk-test")
    response = TestClient(api_main.app, root_path="/api").get(f"/api{path}")

    assert response.status_code == 404


def test_api_docs_can_be_enabled_in_production(jwt_api_factory: Callable[..., JwtApi]) -> None:
    api = jwt_api_factory(env="production", openai_api_key="sk-test", expose_api_docs=True)

    assert api.client.get("/openapi.json").status_code == 200


@pytest.mark.parametrize("path", _DOCS_PATHS)
def test_api_docs_are_served_in_development(monkeypatch: pytest.MonkeyPatch, path: str) -> None:
    monkeypatch.setattr(api_main, "settings", Settings(env="development"))
    response = TestClient(api_main.app).get(path)

    assert response.status_code == 200
    assert "content-security-policy" not in response.headers  # Swagger UI loads its assets


def test_openapi_schema_declares_bearer_auth_on_v1_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api_main, "settings", Settings(env="development"))
    schema = TestClient(api_main.app).get("/openapi.json").json()

    assert schema["components"]["securitySchemes"]["bearerAuth"] == {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
    }
    for path, operations in schema["paths"].items():
        for operation in operations.values():
            expected = [{"bearerAuth": []}] if path.startswith("/v1/") else None
            assert operation.get("security") == expected, path


# --- Security headers -------------------------------------------------------------------


@pytest.mark.parametrize("authenticated", [True, False])
def test_v1_responses_carry_security_headers_and_are_not_stored(
    jwt_api_factory: Callable[..., JwtApi], token: dict[str, str], authenticated: bool
) -> None:
    api = jwt_api_factory()
    response = api.client.get("/v1/me/threads", headers=token if authenticated else {})

    assert response.status_code == (200 if authenticated else 401)
    _assert_security_headers(response)
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("path", ["/health/live", "/health/ready"])
def test_health_responses_carry_security_headers(
    jwt_api_factory: Callable[..., JwtApi], path: str
) -> None:
    api = jwt_api_factory()
    response = api.client.get(path)

    _assert_security_headers(response)
    assert "cache-control" not in response.headers


def test_responses_from_request_guards_carry_security_headers(
    jwt_api_factory: Callable[..., JwtApi], token: dict[str, str]
) -> None:
    api = jwt_api_factory(max_request_body_bytes=1024)
    with structlog.testing.capture_logs(
        processors=[structlog.contextvars.merge_contextvars]
    ) as logs:
        response = api.client.post(
            "/v1/agent/invoke",
            headers={**token, "X-Correlation-ID": "too-big-1"},
            json={"message": "x" * 2000},
        )

    assert response.status_code == 413
    _assert_security_headers(response)
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-correlation-id"] == "too-big-1"
    [event] = [log for log in logs if log["event"] == "agent_request_body_too_large"]
    assert event["request_id"] == "too-big-1"


@pytest.mark.parametrize("root_path", ["", "/api"])
@pytest.mark.parametrize("authenticated", [True, False])
def test_rate_limits_apply_to_every_v1_prefix_and_behind_a_root_path(
    jwt_api_factory: Callable[..., JwtApi],
    token: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    root_path: str,
    authenticated: bool,
) -> None:
    """Per-principal limits, and per-IP limits on failed authentication."""
    jwt_api_factory(rate_limit_enabled=True)
    monkeypatch.setattr(
        api_main,
        "rate_limiter",
        InMemoryTokenBucketRateLimiter(capacity=1, requests_per_window=1, window_seconds=3600),
    )
    client = TestClient(api_main.app, root_path=root_path)
    headers = {**(token if authenticated else {}), "X-Correlation-ID": "limited-1"}

    first = client.get(f"{root_path}/v1/me/threads", headers=headers)
    second = client.get(f"{root_path}/v1/me/threads", headers=headers)

    assert first.status_code == (200 if authenticated else 401)
    assert second.status_code == 429
    assert second.headers["x-correlation-id"] == "limited-1"
    assert second.headers["cache-control"] == "no-store"


def test_unhandled_errors_keep_cors_and_security_headers(
    jwt_api_factory: Callable[..., JwtApi],
    token: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = jwt_api_factory(cors_allowed_origins=[_APP_ORIGIN])

    async def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(api.service, "list_user_threads", fail)
    response = api.client.get("/v1/me/threads", headers={**token, "Origin": _APP_ORIGIN})

    assert response.status_code == 500
    assert response.json() == {"detail": "internal_server_error"}
    assert response.headers["access-control-allow-origin"] == _APP_ORIGIN
    assert response.headers["cache-control"] == "no-store"
    assert "x-correlation-id" in response.headers
    _assert_security_headers(response)


def test_v1_paths_behind_a_root_path_are_not_stored(
    jwt_api_factory: Callable[..., JwtApi], token: dict[str, str]
) -> None:
    jwt_api_factory()
    response = TestClient(api_main.app, root_path="/api").get("/api/v1/me/threads", headers=token)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"


def test_hsts_is_sent_only_when_configured(
    jwt_api_factory: Callable[..., JwtApi],
) -> None:
    api = jwt_api_factory(hsts_max_age_seconds=31_536_000)
    response = api.client.get("/health/live")

    assert response.headers["strict-transport-security"] == "max-age=31536000"


def test_stream_headers_work_with_the_documented_nginx_config(
    jwt_api_factory: Callable[..., JwtApi],
    token: dict[str, str],
    stream_replies: Callable[..., Any],
) -> None:
    """OPERATIONS.md relies on `X-Accel-Buffering: no`; hardening must not disturb it."""
    stream_replies(AIMessage(content="streamed"))
    api = jwt_api_factory(cors_allowed_origins=[_APP_ORIGIN])
    response = api.client.post(
        "/v1/agent/stream",
        headers={**token, "Origin": _APP_ORIGIN},
        json={"message": "hi"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-accel-buffering"] == "no"
    assert response.headers.get_list("cache-control") == ["no-store"]
    assert response.headers["access-control-allow-origin"] == _APP_ORIGIN
    _assert_security_headers(response)
    assert "event: done" in response.text


# --- Host header ------------------------------------------------------------------------


def test_unlisted_host_is_rejected_except_for_health_probes(
    jwt_api_factory: Callable[..., JwtApi], token: dict[str, str]
) -> None:
    api = jwt_api_factory(allowed_hosts=["api.example.com"])

    rejected = api.client.get("/v1/me/threads", headers={**token, "Host": "evil.example.com"})
    assert rejected.status_code == 400
    _assert_security_headers(rejected)

    allowed = api.client.get("/v1/me/threads", headers={**token, "Host": "api.example.com"})
    assert allowed.status_code == 200

    # Kubernetes probes address the pod by IP.
    probe = api.client.get("/health/live", headers={"Host": "10.0.0.7:8000"})
    assert probe.status_code == 200
    behind_root_path = TestClient(api_main.app, root_path="/api").get(
        "/api/health/live", headers={"Host": "10.0.0.7:8000"}
    )
    assert behind_root_path.status_code == 200


def test_any_host_is_accepted_when_none_are_configured(
    jwt_api_factory: Callable[..., JwtApi], token: dict[str, str]
) -> None:
    api = jwt_api_factory()
    response = api.client.get("/v1/me/threads", headers={**token, "Host": "anything.example"})

    assert response.status_code == 200


# --- Correlation IDs --------------------------------------------------------------------


def _audited_request_id(api: JwtApi, headers: dict[str, Any]) -> tuple[str, str]:
    """Send an unauthenticated request; return the echoed ID and the `auth_failed` one."""
    with structlog.testing.capture_logs() as logs:
        response = api.client.get("/v1/me/threads", headers=headers)
    assert response.status_code == 401
    [event] = [log for log in logs if log["event"] == "auth_failed"]
    return response.headers["x-correlation-id"], event["request_id"]


def test_well_formed_correlation_id_is_echoed_and_audited(
    jwt_api_factory: Callable[..., JwtApi],
) -> None:
    api = jwt_api_factory()
    echoed, audited = _audited_request_id(api, {"X-Correlation-ID": "client-req.42_a"})

    assert echoed == audited == "client-req.42_a"


@pytest.mark.parametrize(
    "supplied",
    [
        b'x", "event": "auth_succeeded',  # JSON field injection
        b"a b",
        b"id\tforged",
        b"x" * 129,
        "\u00efd".encode(),
        b"",
    ],
)
def test_malformed_correlation_id_is_replaced(
    jwt_api_factory: Callable[..., JwtApi], supplied: bytes
) -> None:
    api = jwt_api_factory()
    echoed, audited = _audited_request_id(api, {"X-Correlation-ID": supplied})

    assert echoed == audited
    assert str(uuid.UUID(audited)) == audited


def test_x_request_id_is_not_used_as_the_correlation_id(
    jwt_api_factory: Callable[..., JwtApi],
) -> None:
    api = jwt_api_factory()
    echoed, audited = _audited_request_id(api, {"X-Request-Id": "forged-request-id"})

    assert echoed == audited
    assert str(uuid.UUID(audited)) == audited
