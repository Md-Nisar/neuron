# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Guard construction, selected by `APP_LIMITS_BACKEND` (ADR 0008 decision 8).

The Protocols and the in-memory guards live in `security/`; this module imports them, never
the reverse. Every guard has a Postgres implementation: the run guard (`persistence/run_guard.py`,
#146), the token budget (`persistence/token_budget.py`, #147) and the request rate limiter
(`persistence/rate_limiter.py`, #148), all on the persistence pool.
"""

from __future__ import annotations

from neuron_agent.config.settings import Settings
from neuron_agent.persistence.checkpointer import Persistence
from neuron_agent.persistence.rate_limiter import PostgresRateLimiter
from neuron_agent.persistence.run_guard import PostgresRunGuard
from neuron_agent.persistence.token_budget import PostgresTokenBudget
from neuron_agent.security.rate_limiter import InMemoryTokenBucketRateLimiter, RateLimiter
from neuron_agent.security.run_guard import InMemoryRunGuard, RunGuard
from neuron_agent.security.usage_budget import InMemoryRollingTokenBudget, TokenBudget


def build_rate_limiter(settings: Settings, persistence: Persistence | None = None) -> RateLimiter:
    """Build one request rate limiter (the API keeps one per key namespace).

    `postgres` shares its buckets through the persistence pool. Its IP keys are HMACs under
    a key derived from `APP_IDENTITY_HASH_KEY`, so the key is required.
    """
    if settings.limits_backend == "postgres":
        if persistence is None or persistence.pool is None:
            raise ValueError("APP_LIMITS_BACKEND=postgres needs the persistence connection pool")
        if settings.rate_limit_enabled and settings.identity_hash_key is None:
            raise ValueError("APP_IDENTITY_HASH_KEY is required for shared rate limits")
        return PostgresRateLimiter(
            persistence.pool,
            capacity=settings.rate_limit_burst,
            requests_per_window=settings.rate_limit_requests_per_window,
            window_seconds=settings.rate_limit_window_seconds,
        )
    return InMemoryTokenBucketRateLimiter(
        capacity=settings.rate_limit_burst,
        requests_per_window=settings.rate_limit_requests_per_window,
        window_seconds=settings.rate_limit_window_seconds,
    )


def build_ip_pre_limiter(settings: Settings) -> RateLimiter | None:
    """The bounded in-memory IP limiter that runs in front of a shared one (None otherwise)."""
    if settings.limits_backend != "postgres":
        return None
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
