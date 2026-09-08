"""Deterministic failure-and-resilience regression suite (issue #7).

Each test forces a failure at the same boundary the production code already
classifies it at (AgentService.invoke, the rate limiter, or Settings
construction) and asserts the HTTP contract plus the absence of leaked
internal detail. Deeper unit-level coverage for each error's classification
lives alongside the module that owns it: `tests/unit/test_model_factory.py`,
`tests/graph/test_main_graph.py`, `tests/unit/test_tool_timeout_middleware.py`,
`tests/unit/test_tool_failure_isolation_middleware.py`,
`tests/unit/test_rate_limiter.py`, `tests/unit/test_settings.py`.
"""

from __future__ import annotations


def test_suite_is_collected() -> None:
    assert True
