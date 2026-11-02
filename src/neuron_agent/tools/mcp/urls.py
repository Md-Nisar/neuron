# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Which MCP server URLs may be used (ADR 0009, decision 5)."""

from __future__ import annotations

from urllib.parse import urlparse

import structlog

from neuron_agent.errors.base import ConfigurationError
from neuron_agent.security.input_policy import validate_safe_url

logger = structlog.get_logger(__name__)

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def is_local_test_server(url: str, *, env: str) -> bool:
    """Whether `url` is a loopback address in development or test (the reference server)."""
    return env in {"development", "test"} and urlparse(url).hostname in _LOOPBACK_HOSTS


def validate_mcp_url(url: str, *, env: str) -> str:
    """Accept an `https` URL that passes `validate_safe_url`; in development and test also a
    loopback URL (the in-repo reference server). Nothing else, `http` included."""
    parsed = urlparse(url)
    if is_local_test_server(url, env=env):
        if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
            raise ConfigurationError("MCP server URL must be http(s) without credentials")
        if parsed.scheme == "http":
            # The only plain-http exception (#366): the loopback reference server.
            logger.warning("mcp_plain_http_allowed", env=env)
        return url
    if parsed.scheme != "https":
        raise ConfigurationError("MCP server URL must use https")
    try:
        return validate_safe_url(url)
    except Exception as exc:
        raise ConfigurationError(f"MCP server URL is not allowed: {exc}") from None
