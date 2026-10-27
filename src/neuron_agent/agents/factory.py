# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Application-level agent factory."""

from __future__ import annotations

from neuron_agent.config.settings import Settings
from neuron_agent.models.factory import create_main_agent
from neuron_agent.tools.registry import builtin_registry


def build_agent(settings: Settings) -> object:
    """Build the production agent with its approved tool set."""
    return create_main_agent(settings, builtin_registry())
