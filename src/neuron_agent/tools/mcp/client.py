# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""MCP client: tool discovery at start-up, one connection per tool call (ADR 0009 decision 5).

The server list and the pinned tool definitions come from the operator's file. Discovery runs
once; a tool that is unlisted or no longer matches its pin is not registered, and later
`list_changed` notifications are never read because no connection is held open. A call opens a
connection, sends the configured bearer token for that server (never the caller's), reads the
reply and closes. The client declares no sampling, roots or elicitation handler, so a server
cannot ask for any of them. A reply is text only and capped; anything else is an error.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any

import httpx2
import structlog
from langchain_core.tools import StructuredTool, ToolException
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp_types import CallToolResult, TextContent
from pydantic import SecretStr

from neuron_agent.security.input_policy import audit_tool_name, validate_safe_url
from neuron_agent.tools.mcp.config import McpConfig, McpServerConfig, McpToolConfig
from neuron_agent.tools.mcp.pins import FetchedTool, check_pins
from neuron_agent.tools.mcp.urls import is_local_test_server
from neuron_agent.tools.registry import ToolSpec

logger = structlog.get_logger(__name__)

_MAX_LIST_PAGES = 10
# What the model sees when a tool's reply cannot be used. The server's own words are untrusted
# and never repeated.
_UNUSABLE_RESULT = "Error: the tool returned an unusable result. Answer without it."


class McpResultError(ToolException):
    """A reply that is an error, holds more than text, or is larger than allowed."""


@asynccontextmanager
async def _connect(
    url: str, *, token: SecretStr | None, env: str, timeout: float
) -> AsyncIterator[Client]:
    if not is_local_test_server(url, env=env):
        validate_safe_url(url)
    headers = {"Authorization": f"Bearer {token.get_secret_value()}"} if token else None
    async with httpx2.AsyncClient(headers=headers, timeout=httpx2.Timeout(timeout)) as http:
        transport = streamable_http_client(url, http_client=http)
        # No sampling, roots, elicitation or logging callback: none is advertised, so the
        # server cannot request any of them. No response cache: every call reaches the server.
        async with Client(transport, read_timeout_seconds=timeout, cache=None) as client:
            yield client


def _text_of(result: CallToolResult, max_bytes: int) -> str:
    if result.is_error:
        raise McpResultError("the MCP tool reported an error")
    texts: list[str] = []
    for block in result.content:
        if not isinstance(block, TextContent):
            raise McpResultError("the MCP tool returned content that is not text")
        texts.append(block.text)
    text = "\n".join(texts)
    if len(text.encode("utf-8")) > max_bytes:
        raise McpResultError("the MCP tool result is larger than allowed")
    return text


def _langchain_tool(
    server: McpServerConfig,
    remote_name: str,
    description: str,
    schema: dict[str, Any],
    *,
    token: SecretStr | None,
    env: str,
    timeout: float,
    max_output_bytes: int,
) -> StructuredTool:
    async def call(**arguments: Any) -> str:
        async with _connect(server.url, token=token, env=env, timeout=timeout) as client:
            result = await client.call_tool(remote_name, arguments)
        return _text_of(result, max_output_bytes)

    return StructuredTool(
        # Prefixed, so a server can never shadow a builtin or another server's tool.
        name=f"mcp_{server.name}_{remote_name}",
        description=description,
        args_schema=schema,
        coroutine=call,
        # Annotations and `_meta` are untrusted hints and are not carried over.
        handle_tool_error=lambda _: _UNUSABLE_RESULT,
    )


async def _list_definitions(client: Client) -> list[FetchedTool]:
    fetched: list[FetchedTool] = []
    cursor: str | None = None
    for _ in range(_MAX_LIST_PAGES):
        page = await client.list_tools(cursor=cursor)
        fetched += [FetchedTool(t.name, t.description, t.input_schema) for t in page.tools]
        cursor = page.next_cursor
        if not cursor:
            return fetched
    raise McpResultError("the MCP server lists too many tool pages")


async def fetch_definitions(
    url: str, *, token: SecretStr | None, env: str, timeout: float
) -> list[FetchedTool]:
    """The tool definitions a server reports now (also used to compute pins)."""
    async with asyncio.timeout(timeout):
        async with _connect(url, token=token, env=env, timeout=timeout) as client:
            return await _list_definitions(client)


def fetch_definitions_blocking(
    url: str, *, token: SecretStr | None, env: str, timeout: float
) -> list[FetchedTool]:
    """`fetch_definitions` for a command line: runs its own event loop."""
    return asyncio.run(fetch_definitions(url, token=token, env=env, timeout=timeout))


async def _discover_server(
    server: McpServerConfig,
    *,
    token: SecretStr | None,
    env: str,
    timeout: float,
    max_output_bytes: int,
) -> list[ToolSpec]:
    fetched = await fetch_definitions(server.url, token=token, env=env, timeout=timeout)
    result = check_pins(server.pins, fetched)
    for problem in result.problems:
        logger.warning(
            "mcp_tool_rejected",
            server=server.name,
            tool=audit_tool_name(problem.tool, server.pins),
            reason=problem.kind,
        )
    wanted: dict[str, McpToolConfig] = {tool.name: tool for tool in server.tools}
    by_name = {tool.name: tool for tool in fetched}
    specs: list[ToolSpec] = []
    for name in result.accepted:
        definition, configured = by_name[name], wanted[name]
        tool = _langchain_tool(
            server,
            name,
            definition.description or "",
            dict(definition.input_schema),
            token=token,
            env=env,
            timeout=timeout,
            max_output_bytes=max_output_bytes,
        )
        specs.append(
            ToolSpec(
                tool,
                scope=f"tools:mcp.{server.name}.{name}",
                risk=configured.risk,
                source="mcp",
            )
        )
    return specs


async def discover_mcp_specs(
    config: McpConfig,
    *,
    tokens: Mapping[str, SecretStr],
    env: str,
    timeout: float,
    max_output_bytes: int,
) -> list[ToolSpec]:
    """Tool specs for every pinned tool the configured servers report.

    A server that cannot be reached, or whose reply is unusable, contributes nothing and is
    logged by name and error type; it never stops start-up or the other servers.
    """
    specs: list[ToolSpec] = []
    for server in config.servers:
        try:
            specs += await _discover_server(
                server,
                token=tokens.get(server.name) if server.auth == "bearer" else None,
                env=env,
                timeout=timeout,
                max_output_bytes=max_output_bytes,
            )
        except Exception as exc:  # one server must not stop start-up or the others
            logger.warning(
                "mcp_server_unavailable", server=server.name, error_type=type(exc).__name__
            )
    return specs
