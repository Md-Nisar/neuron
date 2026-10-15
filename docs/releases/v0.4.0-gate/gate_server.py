"""Release-gate launcher: the real app, with a slow fake model that reports token usage.

Only the chat model is replaced (so runs take GATE_MODEL_DELAY seconds and charge
GATE_MODEL_TOKENS tokens); auth, limits, persistence, audit and HTTP are the real code.
"""
import asyncio
import os
from typing import Any

import uvicorn
from langchain_core.messages import AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk

from neuron_agent.models import factory

DELAY = float(os.environ.get("GATE_MODEL_DELAY", "0"))
TOKENS = int(os.environ.get("GATE_MODEL_TOKENS", "0"))
USAGE = {"input_tokens": TOKENS, "output_tokens": 0, "total_tokens": TOKENS}


class GateModel(factory._FakeChatModel):
    async def _agenerate(self, *args: Any, **kwargs: Any) -> Any:
        await asyncio.sleep(DELAY)
        result = await super()._agenerate(*args, **kwargs)
        result.generations[0].message.usage_metadata = USAGE
        return result

    async def _astream(self, *args: Any, **kwargs: Any) -> Any:
        await asyncio.sleep(DELAY)
        async for chunk in super()._astream(*args, **kwargs):
            yield chunk
        yield ChatGenerationChunk(message=AIMessageChunk(content="", usage_metadata=USAGE))


factory.create_chat_model = lambda settings: GateModel(responses=["Gate response 7f3c."])

from neuron_agent.api.main import app  # noqa: E402  (graph builds at import)

uvicorn.run(app, host="127.0.0.1", port=int(os.environ["GATE_PORT"]), log_level="warning")
