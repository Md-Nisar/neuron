"""Input and tool policy enforcement."""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable
from urllib.parse import urlparse

from neuron_agent.errors.base import AuthorizationError, ValidationAppError

HIGH_RISK_TOOL_NAMES = frozenset({"send_email", "write_file", "delete_record", "execute_payment"})

_ALLOWED_CONTROL_CHARS = frozenset({"\t", "\n", "\r"})


def validate_user_message(message: str, *, max_chars: int) -> str:
    """Normalize and bound user-controlled text before it reaches the graph."""
    normalized = message.strip()
    if not normalized:
        raise ValidationAppError("message must not be empty")
    if len(normalized) > max_chars:
        raise ValidationAppError(f"message exceeds {max_chars} characters")
    if any(
        unicodedata.category(char) == "Cc" and char not in _ALLOWED_CONTROL_CHARS
        for char in normalized
    ):
        raise ValidationAppError("message contains disallowed control characters")
    return normalized


def require_allowed_tool(tool_name: str, allowed_tools: Iterable[str]) -> None:
    """Enforce tool allow-list outside the model loop."""
    if tool_name not in set(allowed_tools):
        raise AuthorizationError(f"tool is not allowed: {tool_name}")
    if tool_name in HIGH_RISK_TOOL_NAMES:
        raise AuthorizationError(f"high-impact tool requires human approval: {tool_name}")


def validate_safe_url(url: str) -> str:
    """Reject URL forms commonly used for SSRF or local file access."""
    parsed = urlparse(url)
    if parsed.scheme not in {"https", "http"}:
        raise ValidationAppError("URL scheme must be http or https")
    if not parsed.hostname:
        raise ValidationAppError("URL must include a hostname")
    hostname = parsed.hostname.lower()
    if hostname in {"localhost", "127.0.0.1", "::1"} or hostname.endswith(".local"):
        raise AuthorizationError("local network URLs are not allowed")
    return url
