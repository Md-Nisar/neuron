"""Agent Server graph for the telemetry gate: the shipped graph, with only the model scripted."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gate_model  # noqa: E402

gate_model.install()

from neuron_agent.graphs.main_graph import graph  # noqa: E402

__all__ = ["graph"]
