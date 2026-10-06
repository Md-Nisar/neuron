"""Transport-independent agent application service."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

import psycopg
import structlog
from langchain_core.messages import HumanMessage

from neuron_agent.config.settings import Settings
from neuron_agent.errors.base import PersistenceError
from neuron_agent.graphs.main_graph import build_graph
from neuron_agent.observability.logging import bind_correlation_context
from neuron_agent.persistence.checkpointer import Persistence, build_persistence
from neuron_agent.schemas.agent import AgentRequest, AgentResponse
from neuron_agent.security.input_policy import validate_user_message

logger = structlog.get_logger(__name__)


class AgentService:
    """Invoke the graph behind a stable application boundary."""

    def __init__(self, settings: Settings, persistence: Persistence | None = None) -> None:
        self._settings = settings
        self._persistence = persistence or build_persistence(settings)
        self._graph: Any | None = None
        if self._persistence.is_open:
            self._graph = build_graph(settings, checkpointer=self._persistence.checkpointer)

    async def startup(self) -> None:
        """Open persistence resources (connection pool) before serving requests."""
        if self._persistence.is_open:
            return
        await self._persistence.open(run_setup=self._settings.checkpointer_setup_on_startup)
        self._graph = build_graph(self._settings, checkpointer=self._persistence.checkpointer)

    async def shutdown(self) -> None:
        """Release persistence resources."""
        if self._persistence.pool is not None:
            await self._persistence.close()
            self._graph = None

    @property
    def graph(self) -> Any:
        """The compiled graph; unavailable until a database-backed service is started."""
        if self._graph is None:
            raise PersistenceError("thread persistence is not started")
        return self._graph

    async def is_ready(self) -> bool:
        """Return whether the service's dependencies are reachable."""
        return await self._persistence.is_ready()

    async def invoke(self, request: AgentRequest) -> AgentResponse:
        request_id = str(uuid.uuid4())
        thread_id = request.thread_id or str(uuid.uuid4())
        run_id = str(uuid.uuid4())
        user_id_hash = _hash_identifier(request.user_id) if request.user_id else None
        message = validate_user_message(request.message, max_chars=self._settings.max_prompt_chars)
        bind_correlation_context(request_id=request_id, thread_id=thread_id, run_id=run_id)
        try:
            result = await self.graph.ainvoke(
                {
                    "messages": [HumanMessage(content=message)],
                    "request_id": request_id,
                    "thread_id": thread_id,
                    "run_id": run_id,
                    "user_id_hash": user_id_hash,
                },
                config={"configurable": {"thread_id": thread_id}},
            )
        except psycopg.Error as exc:
            logger.warning(
                "checkpointer_operation_failed",
                backend=self._persistence.backend,
                error_type=type(exc).__name__,
            )
            raise PersistenceError("thread persistence failed") from exc
        answer = result["answer"]
        return AgentResponse(
            request_id=request_id,
            thread_id=thread_id,
            answer=answer.answer,
            used_tools=answer.used_tools,
            confidence=answer.confidence,
        )


def _hash_identifier(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
