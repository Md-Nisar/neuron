# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Application-level agent factory."""

from __future__ import annotations

from neuron_agent.config.settings import Settings
from neuron_agent.models.factory import create_main_agent
from neuron_agent.tools.registry import ToolRegistry, builtin_registry


async def build_registry(settings: Settings) -> ToolRegistry | None:
    """The builtin tools plus every pinned MCP tool the operator configured (ADR 0009).

    Runs once at start-up. Without `APP_MCP_SERVERS` it returns None (use the builtin tools),
    does no I/O and imports no MCP code.
    """
    if settings.mcp_servers is None:
        return None
    from neuron_agent.tools.mcp.client import discover_mcp_specs
    from neuron_agent.tools.mcp.config import load_mcp_config

    config = load_mcp_config(
        settings.mcp_servers, env=settings.env, token_names=settings.mcp_bearer_tokens
    )
    mcp_specs = await discover_mcp_specs(
        config,
        tokens=settings.mcp_bearer_tokens,
        env=settings.env,
        timeout=float(settings.tool_timeout_seconds),
        max_output_bytes=settings.mcp_max_output_bytes,
    )
    return ToolRegistry([*builtin_registry(), *mcp_specs])


def build_agent(settings: Settings, registry: ToolRegistry | None = None) -> object:
    """Build the production agent with its approved tool set."""
    return create_main_agent(settings, registry or builtin_registry())
