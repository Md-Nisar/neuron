# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Guard construction, selected by `APP_LIMITS_BACKEND` (ADR 0008 decision 8).

The Protocols and the in-memory guards live in `security/`; this module imports them, never
the reverse. The run guard (`persistence/run_guard.py`, #146) and the token budget
(`persistence/token_budget.py`, #147) have Postgres implementations. The request rate limiter
does not (#148), so selecting `postgres` still stops start-up in its builder rather than
silently running without cross-replica rate limits.
"""

from __future__ import annotations

from neuron_agent.config.settings import Settings
from neuron_agent.persistence.checkpointer import Persistence
from neuron_agent.persistence.run_guard import PostgresRunGuard
from neuron_agent.persistence.token_budget import PostgresTokenBudget
from neuron_agent.security.rate_limiter import InMemoryTokenBucketRateLimiter, RateLimiter
from neuron_agent.security.run_guard import InMemoryRunGuard, RunGuard
from neuron_agent.security.usage_budget import InMemoryRollingTokenBudget, TokenBudget


def _require_memory(settings: Settings) -> None:
    """The request rate limiter has no Postgres version yet (#148)."""
    if settings.limits_backend == "postgres":
        raise NotImplementedError(
            "APP_LIMITS_BACKEND=postgres has no request rate limiter implementation yet (#148); "
            "use memory"
        )


def build_rate_limiter(settings: Settings) -> RateLimiter:
    """Build one request rate limiter (the API keeps one per key namespace)."""
    _require_memory(settings)
    return InMemoryTokenBucketRateLimiter(
        capacity=settings.rate_limit_burst,
        requests_per_window=settings.rate_limit_requests_per_window,
        window_seconds=settings.rate_limit_window_seconds,
    )


def build_token_budget(settings: Settings, persistence: Persistence | None = None) -> TokenBudget:
    """Build the token budget; `postgres` shares its ledger through the persistence pool."""
    if settings.limits_backend == "postgres":
        if persistence is None or persistence.pool is None:
            raise ValueError("APP_LIMITS_BACKEND=postgres needs the persistence connection pool")
        return PostgresTokenBudget(
            persistence.pool,
            token_limit=settings.user_token_budget,
            window_seconds=settings.user_token_budget_window_seconds,
            max_concurrent_reserves_per_owner=max(2, 2 * settings.max_concurrent_runs_per_user),
        )
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
