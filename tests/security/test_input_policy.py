from __future__ import annotations

import pytest

from neuron_agent.errors.base import AuthorizationError, ValidationAppError
from neuron_agent.security.input_policy import (
    require_allowed_tool,
    validate_safe_url,
    validate_user_message,
)


def test_validate_user_message_rejects_empty() -> None:
    with pytest.raises(ValidationAppError):
        validate_user_message("  ", max_chars=10)


def test_validate_user_message_rejects_oversized() -> None:
    with pytest.raises(ValidationAppError):
        validate_user_message("x" * 11, max_chars=10)


def test_tool_allow_list_blocks_unknown_tool() -> None:
    with pytest.raises(AuthorizationError):
        require_allowed_tool("delete_record", {"calculator"})


def test_safe_url_rejects_localhost() -> None:
    with pytest.raises(AuthorizationError):
        validate_safe_url("http://localhost:8000/secrets")
