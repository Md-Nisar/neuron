"""Transport-independent agent application service."""

from __future__ import annotations

import hashlib
import uuid

from langchain_core.messages import HumanMessage

from neuron_agent.config.settings import Settings
from neuron_agent.graphs.main_graph import build_graph
from neuron_agent.observability.logging import bind_correlation_context
from neuron_agent.schemas.agent import AgentRequest, AgentResponse
from neuron_agent.security.input_policy import validate_user_message


class AgentService:
    """Invoke the graph behind a stable application boundary."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._graph = build_graph(settings)

    async def invoke(self, request: AgentRequest) -> AgentResponse:
        request_id = str(uuid.uuid4())
        thread_id = request.thread_id or str(uuid.uuid4())
        user_id_hash = _hash_identifier(request.user_id) if request.user_id else None
        message = validate_user_message(request.message, max_chars=self._settings.max_prompt_chars)
        bind_correlation_context(request_id=request_id, thread_id=thread_id)
        result = await self._graph.ainvoke(
            {
                "messages": [HumanMessage(content=message)],
                "request_id": request_id,
                "thread_id": thread_id,
                "user_id_hash": user_id_hash,
            },
            config={
                "configurable": {"thread_id": thread_id},
                "timeout": self._settings.tool_timeout_seconds,
            },
        )
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
