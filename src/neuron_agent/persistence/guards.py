# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Guard construction, selected by `APP_LIMITS_BACKEND` (ADR 0008 decision 8).

The Protocols and the in-memory guards live in `security/`; this module imports them, never
the reverse. Only the run guard has a Postgres implementation so far (`persistence/run_guard.py`,
#146). The request rate limiter and the token budget do not (#147, #148), so selecting
`postgres` still stops start-up in their builders rather than silently running without
cross-replica limits.
"""

from __future__ import annotations

from neuron_agent.config.settings import Settings
from neuron_agent.persistence.checkpointer import Persistence
from neuron_agent.persistence.run_guard import PostgresRunGuard
from neuron_agent.security.rate_limiter import InMemoryTokenBucketRateLimiter, RateLimiter
from neuron_agent.security.run_guard import InMemoryRunGuard, RunGuard
from neuron_agent.security.usage_budget import InMemoryRollingTokenBudget, TokenBudget


def _require_memory(settings: Settings) -> None:
    if settings.limits_backend == "postgres":
        raise NotImplementedError(
            "APP_LIMITS_BACKEND=postgres has no guard implementation yet; use memory"
        )


def build_rate_limiter(settings: Settings) -> RateLimiter:
    """Build one request rate limiter (the API keeps one per key namespace)."""
    _require_memory(settings)
    return InMemoryTokenBucketRateLimiter(
        capacity=settings.rate_limit_burst,
        requests_per_window=settings.rate_limit_requests_per_window,
        window_seconds=settings.rate_limit_window_seconds,
    )


def build_token_budget(settings: Settings) -> TokenBudget:
    _require_memory(settings)
    return InMemoryRollingTokenBudget(
        token_limit=settings.user_token_budget,
        window_seconds=settings.user_token_budget_window_seconds,
    )


def build_run_guard(settings: Settings, persistence: Persistence | None = None) -> RunGuard:
    """Build the run guard; `postgres` shares its leases through the persistence pool."""
    if settings.limits_backend == "postgres":
        if persistence is None or persistence.pool is None:
            raise ValueError("APP_LIMITS_BACKEND=postgres needs the persistence connection pool")
        return PostgresRunGuard(
            persistence.pool,
            max_concurrent_streams=settings.max_concurrent_streams,
            max_concurrent_runs_per_user=settings.max_concurrent_runs_per_user,
            run_timeout_seconds=settings.run_timeout_seconds,
        )
    return InMemoryRunGuard(
        max_concurrent_streams=settings.max_concurrent_streams,
        max_concurrent_runs_per_user=settings.max_concurrent_runs_per_user,
    )
