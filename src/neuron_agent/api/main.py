# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""FastAPI entrypoint."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import importlib
import ipaddress
import json
import math
import secrets
import signal
import sys
import threading
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager, suppress
from types import FrameType
from typing import Annotated, Any

import anyio
import structlog
import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from uvicorn.supervisors import ChangeReload

from neuron_agent.config.settings import Settings, get_settings
from neuron_agent.errors.base import (
    AppError,
    ConcurrentRunsExceededError,
    PersistenceError,
    QuotaExceededError,
    ShuttingDownError,
)
from neuron_agent.observability import metrics
from neuron_agent.observability.audit import audit
from neuron_agent.observability.langsmith_governance import configure_langsmith
from neuron_agent.observability.logging import (
    bind_correlation_context,
    configure_logging,
    log_startup_configuration,
)
from neuron_agent.observability.telemetry import (
    configure_telemetry,
    instrument_app,
    record_correlation_id,
)
from neuron_agent.persistence.checkpointer import build_persistence
from neuron_agent.persistence.guards import build_ip_pre_limiter, build_rate_limiter
from neuron_agent.schemas.agent import (
    AgentRequest,
    AgentResponse,
    ThreadHistoryResponse,
    UserDataErasureResponse,
    UserDataExportResponse,
    UserThreadsResponse,
)
from neuron_agent.security.auth import (
    Principal,
    RequestSecurity,
    check_ip_limits,
    get_shared_token_verifier,
    ip_rate_key,
    persistence_unavailable,
    require_permission,
)
from neuron_agent.services.agent_service import AgentService

settings = get_settings()
configure_logging(
    level=settings.log_level,
    service=settings.name,
    version=settings.version,
    environment=settings.env,
)
logger = structlog.get_logger(__name__)
configure_langsmith(settings)
telemetry = configure_telemetry(settings)
persistence = build_persistence(settings)
service = AgentService(settings, persistence=persistence)
auth_verifier = get_shared_token_verifier(settings)


_READINESS_INTERVAL_SECONDS = 15.0


async def _watch_readiness() -> None:
    """Evaluate readiness every interval for the `neuron.service.ready` gauge; never raises.

    The probe endpoint records nothing, so no external prober is needed and a flood of probe
    requests cannot move the gauge. A failing evaluation is logged once per error type and
    records nothing, so the gauge goes stale and its series disappears.
    """
    failed: set[str] = set()
    while True:
        try:
            metrics.record_readiness(await service.is_ready() and await auth_verifier.ready())
        except Exception as exc:  # the loop must outlive any one failure
            name = type(exc).__name__
            if name not in failed:
                failed.add(name)
                logger.warning("readiness_watch_failed", error_type=name)
        await asyncio.sleep(_READINESS_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    log_startup_configuration(settings)
    await service.startup()
    metrics.quiet_readiness_when(lambda: service.draining)
    watcher = asyncio.create_task(_watch_readiness())
    try:
        yield
    finally:
        watcher.cancel()
        with suppress(asyncio.CancelledError):
            await watcher
        metrics.quiet_readiness_when(None)
        await service.shutdown()
        if telemetry is not None:
            # Flushing can block until the export timeout when the Collector is down.
            await anyio.to_thread.run_sync(telemetry.shutdown)


app = FastAPI(title=settings.name, version=settings.version, lifespan=lifespan)
# Uses the global providers, which are no-ops unless APP_OTEL_ENABLED=true.
instrument_app(app)
# Separate instances, so a flood of junk `ip:` keys cannot evict a principal's bucket.
ip_rate_limiter = build_rate_limiter(settings, persistence)
principal_rate_limiter = build_rate_limiter(settings, persistence)
# In front of a shared `ip_rate_limiter`, so an unauthenticated flood is shed without a
# database write per request (None when the limiter is itself in memory).
ip_pre_limiter = build_ip_pre_limiter(settings)


_RATE_LIMITED_PREFIXES = ("/v1/agent/", "/v1/threads/", "/v1/me/")
_DOCS_PATHS = frozenset({"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"})
# The API only returns JSON and SSE; nothing may load, run or frame its responses.
_CONTENT_SECURITY_POLICY = "default-src 'none'; frame-ancestors 'none'"
_LOG_IDENTITY_KEY = secrets.token_bytes(32)
# On server shutdown, open streams get this long to send their final `error` event.
_STREAM_SHUTDOWN_GRACE_SECONDS = 2.0
# A client that stops reading for this long is disconnected, freeing its run and lease.
_STREAM_SEND_TIMEOUT_SECONDS = 30.0


class _CleanupEventSourceResponse(EventSourceResponse):
    """An `EventSourceResponse` that runs `on_close` however the response ends.

    sse-starlette's `background` hook is skipped when sending fails (the client is gone
    before headers, or `send_timeout` fires). The run lease must still be released, or the
    thread stays busy and the stream slot leaks.
    """

    def __init__(self, *args: Any, on_close: Callable[[], Awaitable[None]], **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._on_close = on_close

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            await self._on_close()


class _RequestBodyLimitMiddleware:
    """Enforce `APP_MAX_REQUEST_BODY_BYTES` on the bytes received, not on `Content-Length`.

    A chunked body has no `Content-Length`, and a declared length can understate the body,
    so the ASGI `receive` channel is read here, before routing and authentication, and
    stops at `limit + 1` bytes (one chunk past the limit at most). The buffered body, at
    most `limit` bytes, is replayed to the app; later `receive` calls (disconnect
    detection on streams) go straight to the server. ADR 0008 decision 5.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = settings.max_request_body_bytes
        declared_size: int | None = None
        for name, value in scope["headers"]:
            if name == b"content-length":
                try:
                    if not (value.isascii() and value.isdigit()):
                        raise ValueError
                    declared_size = int(value)
                except ValueError:
                    await self._reject(scope, receive, send, 400, "validation_error")
                    return
        if declared_size is not None and declared_size > limit:
            logger.warning("agent_request_body_too_large", content_length=declared_size)
            await self._reject(scope, receive, send, 413, "payload_too_large")
            return
        body = bytearray()
        first: Message | None = None
        disconnected: Message | None = None
        while True:
            message = await receive()
            if "body" not in message:  # a disconnect, not body data
                disconnected = message
                break
            first = first or message
            body += message.get("body", b"")
            if len(body) > limit:
                logger.warning(
                    "agent_request_body_too_large", content_length=declared_size, received=len(body)
                )
                await self._reject(scope, receive, send, 413, "payload_too_large")
                return
            if not message.get("more_body", False):
                break
        replay: list[Message] = [disconnected] if disconnected else []
        if first is not None:
            replay.insert(0, {**first, "body": bytes(body), "more_body": False})
        replay_iter = iter(replay)

        async def replayed_receive() -> Message:
            return next(replay_iter, None) or await receive()

        await self.app(scope, replayed_receive, send)

    @staticmethod
    async def _reject(
        scope: Scope, receive: Receive, send: Send, status_code: int, detail: str
    ) -> None:
        await JSONResponse(status_code=status_code, content={"detail": detail})(
            scope, receive, send
        )


app.add_middleware(_RequestBodyLimitMiddleware)


@app.middleware("http")
async def enforce_rate_limit(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    if settings.rate_limit_enabled and _route_path(request.scope).startswith(
        _RATE_LIMITED_PREFIXES
    ):
        if settings.auth_mode == "none":
            key = settings.identity_hash_key
            ip_key = ip_rate_key(_client_ip(request), key.get_secret_value() if key else None)
            try:
                decision = await check_ip_limits(_request_security(), ip_key)
            except PersistenceError as exc:
                failure = persistence_unavailable(exc)
                return JSONResponse(
                    status_code=failure.status_code, content={"detail": failure.detail}
                )
            if not decision.allowed:
                return _rate_limited_response(decision.retry_after_seconds, ip_key)
    return await call_next(request)


@app.middleware("http")
async def bind_request_correlation(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    correlation_id = request.headers.get("X-Correlation-ID")
    if (
        not correlation_id
        or len(correlation_id) > 128
        or any(
            char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
            for char in correlation_id
        )
    ):
        correlation_id = str(uuid.uuid4())
    request.state.correlation_id = correlation_id
    record_correlation_id(correlation_id)
    structlog.contextvars.clear_contextvars()
    bind_correlation_context(request_id=correlation_id, thread_id=None)
    try:
        response = await call_next(request)
    except Exception as exc:  # noqa: BLE001
        # Answer here rather than in Starlette's outermost error handler, so the 500 still
        # passes through the CORS and security-header middleware.
        logger.exception("request_unhandled_error", error_type=type(exc).__name__)
        response = JSONResponse(status_code=500, content={"detail": "internal_server_error"})
    response.headers["X-Correlation-ID"] = correlation_id
    return response


class _HostAndCorsMiddleware:
    """Apply `APP_ALLOWED_HOSTS` and `APP_CORS_ALLOWED_ORIGINS` from the current `settings`.

    Starlette's middlewares fix their configuration when built, so the stack is rebuilt
    whenever `settings` is replaced (tests swap it per case).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self._built_for: Settings | None = None
        self._stack: ASGIApp = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self._built_for is not settings:
            self._stack = _host_and_cors_stack(self.app, settings)
            self._built_for = settings
        await self._stack(scope, receive, send)


def _host_and_cors_stack(app: ASGIApp, config: Settings) -> ASGIApp:
    stack = app
    if config.cors_allowed_origins:
        # Bearer tokens, not cookies: credentialed CORS stays off.
        stack = CORSMiddleware(
            stack,
            allow_origins=config.cors_allowed_origins,
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "X-Correlation-ID"],
            expose_headers=["Retry-After", "X-Correlation-ID"],
            max_age=600,
        )
    if not config.allowed_hosts:
        return stack
    checked = TrustedHostMiddleware(stack, allowed_hosts=config.allowed_hosts, www_redirect=False)
    unchecked = stack

    async def check_host(scope: Scope, receive: Receive, send: Send) -> None:
        # Platform probes address the instance by IP, so health checks skip the Host check.
        if scope["type"] == "http" and _route_path(scope).startswith("/health/"):
            await unchecked(scope, receive, send)
        else:
            await checked(scope, receive, send)

    return check_host


def _route_path(scope: Scope) -> str:
    """The path routing matches, without any `root_path` prefix a proxy setup adds."""
    path: str = scope["path"]
    root_path: str = scope.get("root_path", "")
    return path.removeprefix(root_path) if root_path else path


app.add_middleware(_HostAndCorsMiddleware)


@app.middleware("http")
async def harden_http_responses(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    path = _route_path(request.scope)
    serving_docs = path in _DOCS_PATHS and bool(settings.expose_api_docs)
    if path in _DOCS_PATHS and not serving_docs:
        response: Response = JSONResponse(status_code=404, content={"detail": "Not Found"})
    else:
        response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    if not serving_docs:
        # The docs pages load Swagger UI and ReDoc assets, so they keep the browser default.
        response.headers["Content-Security-Policy"] = _CONTENT_SECURITY_POLICY
    if path.startswith("/v1/"):
        response.headers["Cache-Control"] = "no-store"
    if settings.hsts_max_age_seconds:
        response.headers["Strict-Transport-Security"] = f"max-age={settings.hsts_max_age_seconds}"
    return response


def _openapi() -> dict[str, Any]:
    """Generate the OpenAPI schema, declaring the bearer scheme every `/v1` route requires."""
    if app.openapi_schema is None:
        schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
        schema.setdefault("components", {})["securitySchemes"] = {
            "bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
        }
        for path, operations in schema["paths"].items():
            if path.startswith("/v1/"):
                for operation in operations.values():
                    operation["security"] = [{"bearerAuth": []}]
        app.openapi_schema = schema
    return app.openapi_schema


app.openapi = _openapi  # type: ignore[method-assign]


def _client_ip(request: Request) -> str:
    """Rate-limit key for the client: X-Forwarded-For counts only behind a trusted proxy.

    IPv4-mapped IPv6 is unmapped and IPv6 is aggregated by /64, so one subscriber cannot
    mint a fresh bucket per address. Walking the header from the right stops at the first
    unparseable entry, because nothing to its left can be trusted.
    """
    peer = request.client.host if request.client else "unknown"
    try:
        address = _unmapped(ipaddress.ip_address(peer))
    except ValueError:
        return peer
    if _trusted_proxy(address):
        entries = ",".join(request.headers.getlist("X-Forwarded-For")).split(",")
        while entries and _trusted_proxy(address):
            try:
                address = _unmapped(ipaddress.ip_address(entries.pop().strip()))
            except ValueError:
                break
    if isinstance(address, ipaddress.IPv6Address):
        return str(ipaddress.IPv6Network((int(address), 64), strict=False))
    return str(address)


def _unmapped(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def _trusted_proxy(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    for proxy in settings.trusted_proxies:
        try:
            if address in ipaddress.ip_network(proxy, strict=False):
                return True
        except ValueError:
            continue
    return False


def _rate_limited_response(retry_after_seconds: float, key: str) -> JSONResponse:
    retry_after = max(1, math.ceil(retry_after_seconds))
    metrics.record_policy_block("request_rate")
    logger.warning(
        "user_limit_exceeded",
        limit_type="request_rate",
        owner_key_prefix=_opaque_identity_prefix(key),
        retry_after=retry_after,
    )
    audit(
        "limit_exceeded",
        outcome="denied",
        issuer_id=settings.auth_issuer_id,
        action="request",
        resource_type="api",
        reason="request_rate",
    )
    return JSONResponse(
        status_code=429,
        content={"detail": "rate_limited"},
        headers={"Retry-After": str(retry_after)},
    )


def _opaque_identity_prefix(key: str) -> str:
    return hmac.new(_LOG_IDENTITY_KEY, key.encode(), hashlib.sha256).hexdigest()[:12]


def _request_security() -> RequestSecurity:
    """The request dependencies' view of this module, read at call time (tests swap them)."""
    return RequestSecurity(
        settings=settings,
        verifier=auth_verifier,
        ip_limiter=ip_rate_limiter,
        principal_limiter=principal_rate_limiter,
        ip_pre_limiter=ip_pre_limiter,
        is_rate_limited=lambda request: (
            settings.rate_limit_enabled
            and _route_path(request.scope).startswith(_RATE_LIMITED_PREFIXES)
        ),
        client_ip=_client_ip,
        log_prefix=_opaque_identity_prefix,
    )


app.state.request_security = _request_security


@app.exception_handler(RequestValidationError)
async def handle_request_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    # Only each error's type and location: pydantic's `input` would log the request text.
    errors = [{"type": e["type"], "loc": e["loc"]} for e in exc.errors()]
    logger.warning("agent_request_validation_failed", errors=errors)
    return JSONResponse(status_code=422, content={"detail": "validation_error"})


@app.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
async def ready() -> JSONResponse:
    if not await service.is_ready() or not await auth_verifier.ready():
        return JSONResponse(status_code=503, content={"status": "not_ready"})
    return JSONResponse(content={"status": "ready", "environment": settings.env})


@app.post(
    "/v1/agent/invoke",
    response_model=AgentResponse,
)
async def invoke_agent(
    request: AgentRequest,
    principal: Annotated[Principal | None, Depends(require_permission("agent:invoke"))] = None,
) -> AgentResponse:
    request_id = None
    thread_id = request.thread_id
    bind_correlation_context(request_id=request_id, thread_id=thread_id)
    started = time.monotonic()
    try:
        # Preserve the pre-auth service call shape for local mode and direct
        # callers; authenticated requests always carry the verified principal.
        response = (
            await service.invoke(request)
            if principal is None
            else await service.invoke(request, principal=principal)
        )
        request_id = response.request_id
        thread_id = response.thread_id
        bind_correlation_context(request_id=request_id, thread_id=thread_id)
        logger.info(
            "agent_request_completed",
            request_id=request_id,
            thread_id=thread_id,
            confidence=response.confidence,
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )
        return response
    except AppError as exc:
        metrics.record_error(exc.context.code)
        logger.warning(
            "agent_request_failed",
            request_id=request_id,
            thread_id=thread_id,
            error_code=exc.context.code,
            error_type=type(exc).__name__,
            retryable=exc.context.retryable,
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )
        detail = exc.context.code if exc.context.user_visible else "internal_server_error"
        raise HTTPException(
            status_code=exc.context.http_status, detail=detail, headers=_retry_headers(exc)
        ) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "agent_request_unexpected_error",
            request_id=request_id,
            thread_id=thread_id,
            error_type=type(exc).__name__,
            retryable=False,
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )
        raise HTTPException(status_code=500, detail="internal_server_error") from exc


@app.post("/v1/agent/stream")
async def stream_agent(
    request: AgentRequest,
    principal: Annotated[Principal | None, Depends(require_permission("agent:invoke"))] = None,
) -> EventSourceResponse:
    """Stream a run as server-sent events (ADR 0005, decision 4).

    Validation, rate limiting and thread resolution happen before the first byte, so those
    failures use normal HTTP status codes. Failures after the stream starts become a single
    `error` event followed by `done`.
    """
    bind_correlation_context(request_id=None, thread_id=request.thread_id)
    try:
        run = (
            await service.prepare(request, streaming=True)
            if principal is None
            else await service.prepare(request, streaming=True, principal=principal)
        )
    except AppError as exc:
        metrics.record_error(exc.context.code)
        logger.warning(
            "stream_rejected",
            termination=exc.context.code,
            thread_id=request.thread_id,
            error_code=exc.context.code,
            error_type=type(exc).__name__,
        )
        detail = exc.context.code if exc.context.user_visible else "internal_server_error"
        raise HTTPException(
            status_code=exc.context.http_status, detail=detail, headers=_retry_headers(exc)
        ) from exc

    shutdown = anyio.Event()
    stream = service.stream(run, stop=shutdown)

    async def events() -> AsyncIterator[dict[str, str]]:
        async for event in stream:
            yield {"event": event.event, "data": json.dumps(event.data)}

    async def close() -> None:
        # Closing the generator cancels its run if still active; the lease is released even
        # if the generator never started.
        try:
            await stream.aclose()
        finally:
            await run.lease.release()

    return _CleanupEventSourceResponse(
        events(),
        ping=settings.stream_heartbeat_seconds,
        shutdown_event=shutdown,
        shutdown_grace_period=_STREAM_SHUTDOWN_GRACE_SECONDS,
        send_timeout=_STREAM_SEND_TIMEOUT_SECONDS,
        on_close=close,
    )


# Pre-auth caller identity for body-less thread endpoints; replaced by authentication in
# v0.4.0. A header rather than a query parameter keeps it out of URLs and access logs.
_UserIdHeader = Header(default=None, alias="X-User-Id", max_length=128)


@app.get(
    "/v1/threads/{thread_id}/messages",
    response_model=ThreadHistoryResponse,
)
async def get_thread_messages(
    thread_id: uuid.UUID,
    principal: Annotated[Principal | None, Depends(require_permission("threads:read"))] = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user_id: str | None = _UserIdHeader,
) -> ThreadHistoryResponse:
    """Return a page of a thread's user/assistant turns (ADR 0005, decision 7)."""
    try:
        if principal is None:
            return await service.get_history(str(thread_id), user_id, limit=limit, offset=offset)
        return await service.get_history(
            str(thread_id), user_id, limit=limit, offset=offset, principal=principal
        )
    except AppError as exc:
        raise _http_error("thread_history_failed", exc) from exc


@app.delete("/v1/threads/{thread_id}", status_code=204)
async def delete_thread(
    thread_id: uuid.UUID,
    principal: Annotated[Principal | None, Depends(require_permission("threads:delete"))] = None,
    user_id: str | None = _UserIdHeader,
) -> Response:
    """Delete all stored state for a thread (ADR 0005, decision 7)."""
    try:
        if principal is None:
            await service.delete_thread(str(thread_id), user_id)
        else:
            await service.delete_thread(str(thread_id), user_id, principal=principal)
    except AppError as exc:
        raise _http_error("thread_delete_failed", exc) from exc
    return Response(status_code=204)


@app.get("/v1/me/threads", response_model=UserThreadsResponse)
async def list_my_threads(
    principal: Annotated[Principal | None, Depends(require_permission("threads:read"))] = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user_id: str | None = _UserIdHeader,
) -> UserThreadsResponse:
    """List this caller's threads without exposing conversation contents."""
    try:
        return await service.list_user_threads(
            user_id, limit=limit, offset=offset, principal=principal
        )
    except AppError as exc:
        raise _http_error("user_threads_list_failed", exc) from exc


@app.get("/v1/me/export", response_model=UserDataExportResponse)
async def export_my_data(
    principal: Annotated[Principal | None, Depends(require_permission("threads:read"))] = None,
    limit: int = Query(default=5, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    message_limit: int = Query(default=20, ge=1, le=100),
    message_offset: int = Query(default=0, ge=0),
    user_id: str | None = _UserIdHeader,
) -> UserDataExportResponse:
    """Export paginated user/assistant turns, capped by APP_USER_DATA_EXPORT_MAX_BYTES."""
    try:
        return await service.export_user_data(
            user_id,
            limit=limit,
            offset=offset,
            message_limit=message_limit,
            message_offset=message_offset,
            principal=principal,
        )
    except AppError as exc:
        raise _http_error("user_data_export_failed", exc) from exc


@app.delete("/v1/me/threads", response_model=UserDataErasureResponse)
async def erase_my_threads(
    principal: Annotated[Principal | None, Depends(require_permission("threads:delete"))] = None,
    user_id: str | None = _UserIdHeader,
) -> UserDataErasureResponse:
    """Delete all discoverable caller-owned threads; active threads are skipped."""
    try:
        return await service.erase_user_data(user_id, principal=principal)
    except AppError as exc:
        raise _http_error("user_data_erasure_failed", exc) from exc


def _http_error(event: str, exc: AppError) -> HTTPException:
    """Log and count an `AppError`, and map it to an HTTP error, hiding non-user-visible detail."""
    metrics.record_error(exc.context.code)
    logger.warning(
        event,
        error_code=exc.context.code,
        error_type=type(exc).__name__,
        retryable=exc.context.retryable,
    )
    detail = exc.context.code if exc.context.user_visible else "internal_server_error"
    return HTTPException(
        status_code=exc.context.http_status, detail=detail, headers=_retry_headers(exc)
    )


def _retry_headers(exc: AppError) -> dict[str, str] | None:
    if isinstance(exc, QuotaExceededError):
        return {"Retry-After": str(exc.retry_after_seconds)}
    if isinstance(exc, ConcurrentRunsExceededError | ShuttingDownError):
        # Shutting down: a retry goes to another instance once the platform routes there.
        return {"Retry-After": "1"}
    return None


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def uvicorn_options(config: Settings) -> dict[str, Any]:
    """Uvicorn's configuration, built from `Settings` (ADR 0008, decision 3).

    One process, no `workers`. Uvicorn's own proxy-header rewriting is off so `_client_ip`
    stays the only place `X-Forwarded-For` is parsed, driven by `APP_TRUSTED_PROXIES`.
    """
    return {
        "app": "neuron_agent.api.main:app",
        "host": config.host,
        "port": config.port,
        "timeout_graceful_shutdown": config.run_timeout_seconds + 10,
        "proxy_headers": False,
        "reload": config.env == "development" and _is_loopback(config.host),
    }


class _DrainingServer(uvicorn.Server):
    """A Uvicorn server that starts draining the service when it is told to stop.

    Overrides `Server.handle_exit(sig, frame)`, the handler Uvicorn 0.53 installs for
    SIGINT and SIGTERM (`capture_signals`). It calls `AgentService.begin_drain()` first, so
    `/health/ready` turns 503 before Uvicorn stops accepting connections. On SIGTERM the
    real stop is then delayed by `APP_SHUTDOWN_DRAIN_SECONDS`, so the platform keeps
    routing to a listening socket while it converges; Uvicorn's graceful timeout
    (`APP_RUN_TIMEOUT_SECONDS + 10`) starts after that delay. A second SIGTERM, a SIGINT
    or a zero delay skips the delay and starts Uvicorn's graceful shutdown at once (no
    force); only a SIGINT while `should_exit` is already set forces the exit. Open streams
    are ended by sse-starlette from the delayed `super().handle_exit`, so they keep running
    for the drain delay.
    """

    def __init__(self, config: uvicorn.Config, *, drain_seconds: float) -> None:
        super().__init__(config)
        self._drain_seconds = drain_seconds
        self._exit_scheduled = False

    @contextmanager
    def capture_signals(self) -> Iterator[None]:
        """Uvicorn re-raises a captured SIGTERM once it has shut down, which would end the
        process by that signal (status 143). SIGTERM is ignored while Uvicorn captures it,
        so Uvicorn restores "ignore" and its re-raise is a no-op: a clean shutdown exits 0.
        """
        if threading.current_thread() is not threading.main_thread():
            with super().capture_signals():
                yield
            return
        previous = signal.signal(signal.SIGTERM, signal.SIG_IGN)
        try:
            with super().capture_signals():
                yield
        finally:
            signal.signal(signal.SIGTERM, signal.SIG_DFL if previous is None else previous)

    def handle_exit(self, sig: int, frame: FrameType | None) -> None:
        # Under `python -m` this module is `__main__` while Uvicorn serves the app from the
        # imported copy; the service that answers requests is that copy's.
        importlib.import_module("neuron_agent.api.main").service.begin_drain()
        if (
            sig == signal.SIGTERM
            and self._drain_seconds > 0
            and not self._exit_scheduled
            and not self.should_exit
        ):
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                pass
            else:
                self._exit_scheduled = True
                # From a signal handler only call_soon_threadsafe is safe on a running loop.
                loop.call_soon_threadsafe(
                    loop.call_later, self._drain_seconds, super().handle_exit, sig, frame
                )
                return
        super().handle_exit(sig, frame)


def build_server(config: Settings, **overrides: Any) -> uvicorn.Server:
    """The server `main()` runs; `overrides` replace Uvicorn options (tests bind port 0)."""
    options = {**uvicorn_options(config), **overrides}
    uvicorn_config = uvicorn.Config(**options)
    # Each development reload restart would otherwise wait out the delay.
    drain = 0.0 if uvicorn_config.should_reload else config.shutdown_drain_seconds
    return _DrainingServer(uvicorn_config, drain_seconds=drain)


def _run(server: uvicorn.Server) -> None:
    """Run `server` as `uvicorn.run` would for one process, with or without reload."""
    config = server.config
    try:
        if config.should_reload:
            ChangeReload(config, target=server.run, sockets=[config.bind_socket()]).run()
        else:
            server.run()
    except KeyboardInterrupt:
        pass
    if not server.started and not config.should_reload:
        sys.exit(3)  # Uvicorn's STARTUP_FAILURE


def main() -> None:
    if not _is_loopback(settings.host) and "env" not in settings.model_fields_set:
        # Unset, APP_ENV means development with no authentication.
        raise SystemExit(
            f"Refusing to bind {settings.host}: set APP_ENV explicitly for a non-loopback host."
        )
    _run(build_server(settings))


if __name__ == "__main__":
    main()
