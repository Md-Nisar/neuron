# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""The operator's MCP server list (`APP_MCP_SERVERS`, ADR 0009 decision 5).

Servers come only from this file, never from a request or the model. Anything that would run
code or reach a server some other way is refused at load: stdio, SSE and WebSocket entries,
unknown keys, a plain-http or non-public URL. The loader reads the file and returns validated
data; it opens no connection.
"""

from __future__ import annotations

import json
import re
from collections.abc import Collection
from pathlib import Path
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

from neuron_agent.errors.base import ConfigurationError
from neuron_agent.tools.mcp.pins import PIN_PREFIX
from neuron_agent.tools.mcp.urls import validate_mcp_url

MAX_SERVERS = 8
MAX_TOOLS_PER_SERVER = 32
_PIN = re.compile(re.escape(PIN_PREFIX) + r"[0-9a-f]{64}")
# Names become part of a tool name and a scope (`mcp_<server>_<tool>`, `tools:mcp.<server>.<tool>`).
# A server name has no underscore, so the first `_` after `mcp_` ends it and two servers can never
# produce the same tool name. The longest tool name, 4 + 16 + 1 + 40 characters, fits the 64 that
# model providers allow.
_Name = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9]{0,15}$")]
_ToolName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,39}$")]
_REFUSED_KEYS = {
    "command": "stdio servers run a subprocess from configuration and are not supported",
    "args": "stdio servers run a subprocess from configuration and are not supported",
    "transport": "only Streamable HTTP is supported; do not set a transport",
    "headers": "send a bearer token through APP_MCP_BEARER_TOKENS, not custom headers",
}


class McpToolConfig(BaseModel):
    """A tool the operator exposes, with the pin of the definition they reviewed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: _ToolName
    pin: str
    # Anything a server could change after review is `mutating` until the operator says otherwise.
    risk: Literal["read", "mutating"] = "mutating"

    @field_validator("pin")
    @classmethod
    def _pin_shape(cls, value: str) -> str:
        if not _PIN.fullmatch(value):
            raise ValueError("pin must be 'sha256:' and 64 lowercase hex digits")
        return value


class McpServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: _Name
    url: str
    auth: Literal["bearer", "none"] = "bearer"
    tools: Annotated[list[McpToolConfig], Field(min_length=1, max_length=MAX_TOOLS_PER_SERVER)]

    @model_validator(mode="before")
    @classmethod
    def _refuse_other_transports(cls, data: object) -> object:
        if isinstance(data, dict):
            for key, reason in _REFUSED_KEYS.items():
                if key in data:
                    raise ValueError(f"'{key}' is refused: {reason}")
        return data

    @model_validator(mode="after")
    def _unique_tools(self) -> McpServerConfig:
        names = [tool.name for tool in self.tools]
        if len(set(names)) != len(names):
            raise ValueError(f"server {self.name} lists a tool twice")
        return self

    @property
    def pins(self) -> dict[str, str]:
        return {tool.name: tool.pin for tool in self.tools}


class McpConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    servers: Annotated[list[McpServerConfig], Field(max_length=MAX_SERVERS)]

    @model_validator(mode="after")
    def _unique_servers(self) -> McpConfig:
        names = [server.name for server in self.servers]
        if len(set(names)) != len(names):
            raise ValueError("a server name is used twice")
        return self


def parse_mcp_config(text: str, *, env: str, token_names: Collection[str]) -> McpConfig:
    """Validate the file's content for `env`, given the server names that have a bearer token.

    The error names the problem, never a secret.
    """
    try:
        config = McpConfig.model_validate(json.loads(text))
    except json.JSONDecodeError:
        raise ConfigurationError("APP_MCP_SERVERS is not valid JSON") from None
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in err['loc'])}: {err['msg']}" for err in exc.errors()
        )
        raise ConfigurationError(f"APP_MCP_SERVERS is invalid: {problems}") from None
    for server in config.servers:
        validate_mcp_url(server.url, env=env)
        if server.auth == "bearer" and server.name not in token_names:
            raise ConfigurationError(
                f"MCP server {server.name} needs a token in APP_MCP_BEARER_TOKENS"
            )
    return config


def load_mcp_config(path: Path | None, *, env: str, token_names: Collection[str]) -> McpConfig:
    """The configured servers, or none when `APP_MCP_SERVERS` (`path`) is unset."""
    if path is None:
        return McpConfig(servers=[])
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        raise ConfigurationError("APP_MCP_SERVERS cannot be read") from None
    return parse_mcp_config(text, env=env, token_names=token_names)
