"""FastAPI entrypoint."""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable

import structlog
import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from neuron_agent.config.settings import get_settings
from neuron_agent.errors.base import AppError
from neuron_agent.observability.logging import bind_correlation_context, configure_logging
from neuron_agent.schemas.agent import AgentRequest, AgentResponse
from neuron_agent.services.agent_service import AgentService

settings = get_settings()
configure_logging(
    level=settings.log_level,
    service=settings.name,
    version=settings.version,
    environment=settings.env,
)
logger = structlog.get_logger(__name__)
app = FastAPI(title=settings.name, version=settings.version)
service = AgentService(settings)


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
async def ready() -> dict[str, str]:
    return {"status": "ready", "environment": settings.env}


@app.post("/v1/agent/invoke", response_model=AgentResponse)
async def invoke_agent(request: AgentRequest) -> AgentResponse:
    request_id = None
    thread_id = request.thread_id
    bind_correlation_context(request_id=request_id, thread_id=thread_id)
    try:
        response = await service.invoke(request)
        request_id = response.request_id
        thread_id = response.thread_id
        bind_correlation_context(request_id=request_id, thread_id=thread_id)
        logger.info(
            "agent_request_completed",
            request_id=request_id,
            thread_id=thread_id,
            confidence=response.confidence,
        )
        return response
    except AppError as exc:
        logger.warning(
            "agent_request_failed",
            request_id=request_id,
            thread_id=thread_id,
            error_code=exc.context.code,
            retryable=exc.context.retryable,
        )
        detail = exc.context.code if exc.context.user_visible else "internal_server_error"
        raise HTTPException(status_code=exc.context.http_status, detail=detail) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "agent_request_unexpected_error",
            request_id=request_id,
            thread_id=thread_id,
            retryable=False,
        )
        raise HTTPException(status_code=500, detail="internal_server_error") from exc


def main() -> None:
    uvicorn.run(
        "neuron_agent.api.main:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        reload=settings.env == "development",
    )


if __name__ == "__main__":
    main()
