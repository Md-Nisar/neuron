# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Time-related read-only tools."""

from __future__ import annotations

from datetime import UTC, datetime

from langchain_core.tools import tool


@tool
def utc_now() -> str:
    """Return the current UTC timestamp in ISO 8601 format."""
    return datetime.now(tz=UTC).isoformat()
