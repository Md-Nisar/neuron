"""FastAPI entrypoint."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import math
import os
import secrets
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Any

import anyio
import structlog
import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse
from starlette.types import Receive, Scope, Send

from neuron_agent.config.settings import get_settings
from neuron_agent.errors.base import AppError, ConcurrentRunsExceededError, QuotaExceededError
from neuron_agent.observability.audit import audit
from neuron_agent.observability.logging import bind_correlation_context, configure_logging
from neuron_agent.schemas.agent import AgentRequest, AgentResponse, ThreadHistoryResponse
from neuron_agent.security.auth import (
    Principal,
    get_shared_token_verifier,
    require_permission,
)
from neuron_agent.security.rate_limiter import InMemoryTokenBucketRateLimiter
from neuron_agent.services.agent_service import AgentService

settings = get_settings()
configure_logging(
    level=settings.log_level,
    service=settings.name,
    version=settings.version,
    environment=settings.env,
)
logger = structlog.get_logger(__name__)
service = AgentService(settings)
auth_verifier = get_shared_token_verifier(settings)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await service.startup()
    try:
        yield
    finally:
        await service.shutdown()


app = FastAPI(title=settings.name, version=settings.version, lifespan=lifespan)
rate_limiter = InMemoryTokenBucketRateLimiter(
    capacity=settings.rate_limit_burst,
    requests_per_window=settings.rate_limit_requests_per_window,
    window_seconds=settings.rate_limit_window_seconds,
)


_RATE_LIMITED_PREFIXES = ("/v1/agent/", "/v1/threads/")
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


@app.middleware("http")
async def bind_request_correlation(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    correlation_id = request.headers.get("X-Correlation-ID")
    if (
        correlation_id is None
        or len(correlation_id) > 128
        or any(
            char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
            for char in correlation_id
        )
    ):
        correlation_id = str(uuid.uuid4())
    request.state.correlation_id = correlation_id
    structlog.contextvars.clear_contextvars()
    bind_correlation_context(request_id=correlation_id, thread_id=None)
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = correlation_id
    return response


@app.middleware("http")
async def limit_request_body_size(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_size = int(content_length)
        except ValueError:
            return JSONResponse(status_code=400, content={"detail": "validation_error"})
        if declared_size > settings.max_request_body_bytes:
            logger.warning("agent_request_body_too_large", content_length=declared_size)
            return JSONResponse(status_code=413, content={"detail": "payload_too_large"})
    return await call_next(request)


@app.middleware("http")
async def enforce_rate_limit(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    if settings.rate_limit_enabled and request.url.path.startswith(_RATE_LIMITED_PREFIXES):
        if settings.auth_mode == "none":
            decision = rate_limiter.check(f"ip:{_client_ip(request)}")
            if not decision.allowed:
                return _rate_limited_response(
                    decision.retry_after_seconds, f"ip:{_client_ip(request)}"
                )
    return await call_next(request)


def _client_ip(request: Request) -> str:
    """Use X-Forwarded-For only when the immediate peer is a configured trusted proxy."""
    peer = request.client.host if request.client else "unknown"
    try:
        address = ipaddress.ip_address(peer)
    except ValueError:
        return peer
    trusted = _trusted_proxy(address)
    if not trusted:
        return str(address)
    chain: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for candidate in request.headers.get("X-Forwarded-For", "").split(","):
        try:
            chain.append(ipaddress.ip_address(candidate.strip()))
        except (TypeError, ValueError):
            continue
    while chain and _trusted_proxy(address):
        address = chain.pop()
    return str(address)


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


@app.exception_handler(RequestValidationError)
async def handle_request_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    logger.warning("agent_request_validation_failed", errors=exc.errors())
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
            run.lease.release()

    return _CleanupEventSourceResponse(
        events(),
        ping=settings.stream_heartbeat_seconds,
        headers={"Cache-Control": "no-cache"},
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


def _http_error(event: str, exc: AppError) -> HTTPException:
    """Log an `AppError` and map it to an HTTP error, hiding non-user-visible detail."""
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
    if isinstance(exc, ConcurrentRunsExceededError):
        return {"Retry-After": "1"}
    return None


def main() -> None:
    uvicorn.run(
        "neuron_agent.api.main:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        reload=settings.env == "development",
    )


if __name__ == "__main__":
    main()
