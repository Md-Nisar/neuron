"""FastAPI launcher for the telemetry gate: the real app, with only the chat model scripted."""

import os
import sys

import uvicorn

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gate_model  # noqa: E402

gate_model.install()

from neuron_agent.api.main import app  # noqa: E402  (graph builds at import)

uvicorn.run(app, host="127.0.0.1", port=int(os.environ["GATE_PORT"]), log_level="warning")
