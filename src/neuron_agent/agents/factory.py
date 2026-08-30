"""Application-level agent factory."""

from __future__ import annotations

from neuron_agent.config.settings import Settings
from neuron_agent.models.factory import create_main_agent
from neuron_agent.tools import calculator, utc_now


def build_agent(settings: Settings) -> object:
    """Build the production agent with its approved tool set."""
    return create_main_agent(settings, tools=[utc_now, calculator])
