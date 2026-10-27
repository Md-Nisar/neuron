# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Metric instruments and views (ADR 0007, decision 2).

Instruments come from the global meter provider, which is a no-op unless telemetry is
enabled. Every recording function takes only allow-listed attribute values
(`semconv.METRIC_ATTRIBUTE_ALLOW_LIST`); users, owner keys, threads, runs and requests never
label a metric. Durations are seconds.
"""

from __future__ import annotations

import functools
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from opentelemetry import metrics
from opentelemetry.metrics import CallbackOptions, Observation
from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation, View
from opentelemetry.util.types import AttributeValue

from neuron_agent.observability import semconv

_INSTRUMENTATION_NAME = "neuron_agent"

# Histogram bucket upper bounds, in seconds. LLM latencies run from tens of milliseconds
# (time to first token) to the run timeout; the last bound covers `APP_RUN_TIMEOUT_SECONDS`
# up to its 120 s ceiling. Anything slower falls in the overflow bucket.
LLM_LATENCY_BUCKETS = (
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.0,
    4.0,
    8.0,
    15.0,
    30.0,
    60.0,
    120.0,
)
# Tool calls (bounded by `APP_TOOL_TIMEOUT_SECONDS`, at most 60 s) and checkpoint reads and
# writes are mostly far faster than model calls.
FAST_OPERATION_BUCKETS = (
    0.001,
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
    60.0,
)
# Token counts per model call, powers of 4 as the GenAI conventions advise.
TOKEN_BUCKETS = tuple(float(4**n) for n in range(14))

_HTTP_ATTRIBUTES = {semconv.HTTP_ROUTE, semconv.HTTP_RESPONSE_STATUS_CODE}

Attributes = dict[str, AttributeValue]


def metric_views() -> list[View]:
    """Explicit histogram buckets, plus the attributes each HTTP instrument may keep.

    The FastAPI instrumentation would otherwise label HTTP metrics with the method, scheme
    and protocol version too; only the route template and status code are allow-listed.
    """
    latency = ExplicitBucketHistogramAggregation(LLM_LATENCY_BUCKETS)
    fast = ExplicitBucketHistogramAggregation(FAST_OPERATION_BUCKETS)
    return [
        View(instrument_name=semconv.METRIC_OPERATION_DURATION, aggregation=latency),
        View(instrument_name=semconv.METRIC_RUN_DURATION, aggregation=latency),
        View(instrument_name=semconv.METRIC_STREAM_TTFT, aggregation=latency),
        View(instrument_name=semconv.METRIC_TOOL_DURATION, aggregation=fast),
        View(instrument_name=semconv.METRIC_CHECKPOINT_DURATION, aggregation=fast),
        View(
            instrument_name=semconv.METRIC_USAGE,
            aggregation=ExplicitBucketHistogramAggregation(TOKEN_BUCKETS),
        ),
        View(
            instrument_name=semconv.METRIC_HTTP_REQUEST_DURATION,
            aggregation=latency,
            attribute_keys=_HTTP_ATTRIBUTES,
        ),
        View(
            instrument_name=semconv.METRIC_HTTP_REQUEST_BODY_SIZE, attribute_keys=_HTTP_ATTRIBUTES
        ),
        View(
            instrument_name=semconv.METRIC_HTTP_RESPONSE_BODY_SIZE,
            attribute_keys=_HTTP_ATTRIBUTES,
        ),
        View(instrument_name=semconv.METRIC_HTTP_ACTIVE_REQUESTS, attribute_keys=set()),
    ]


@dataclass(frozen=True)
class _Instruments:
    operation_duration: metrics.Histogram
    token_usage: metrics.Histogram
    run_duration: metrics.Histogram
    stream_ttft: metrics.Histogram
    tool_duration: metrics.Histogram
    errors: metrics.Counter
    policy_blocks: metrics.Counter
    model_fallbacks: metrics.Counter
    approvals: metrics.Counter
    memory_operations: metrics.Counter
    checkpoint_duration: metrics.Histogram
    budget_settle_failures: metrics.Counter
    service_ready: metrics.ObservableGauge
    db_pool_waiting: metrics.ObservableGauge


# State the two observable gauges report. Neither is labelled, and neither holds a user, owner
# key, thread or run: a readiness result and a count of waiting connection requests.
# The readiness result expires: a loop that stopped updating must not keep exporting a stale 1.
READINESS_STALE_SECONDS = 60.0
_monotonic = time.monotonic
_last_ready: tuple[bool, float] | None = None
_quiet_when: Callable[[], bool] | None = None
# One pool source per process (one Persistence per process); a second open replaces the first.
_pool_waiting_source: Callable[[], int] | None = None


def record_readiness(ready: bool) -> None:
    """Remember the latest readiness evaluation, reported as 1 or 0 for the next minute."""
    global _last_ready
    _last_ready = (ready, _monotonic())
    _instruments()  # the gauge exists even when nothing else has been recorded yet


def quiet_readiness_when(predicate: Callable[[], bool] | None) -> None:
    """Report no readiness while `predicate()` is true (a draining instance), instead of a 0."""
    global _quiet_when
    _quiet_when = predicate


def observe_pool_waiting(source: Callable[[], int] | None) -> None:
    """Report `source()` (requests waiting for a pooled connection) each export; None stops."""
    global _pool_waiting_source
    _pool_waiting_source = source
    _instruments()


def _observe_ready(options: CallbackOptions) -> Iterable[Observation]:
    # Nothing before the first evaluation, once it is stale, or while draining: the series then
    # disappears (NeuronNoMetrics territory) instead of reading 0 or a frozen 1.
    if _last_ready is None or _monotonic() - _last_ready[1] > READINESS_STALE_SECONDS:
        return []
    if _quiet_when is not None and _quiet_when():
        return []
    return [Observation(int(_last_ready[0]))]


def _observe_pool_waiting(options: CallbackOptions) -> Iterable[Observation]:
    return [] if _pool_waiting_source is None else [Observation(_pool_waiting_source())]


def _meter() -> metrics.Meter:
    return metrics.get_meter(_INSTRUMENTATION_NAME)


@functools.lru_cache(maxsize=4)
def _build(meter: metrics.Meter) -> _Instruments:
    return _Instruments(
        operation_duration=meter.create_histogram(
            semconv.METRIC_OPERATION_DURATION, unit="s", description="Model call duration"
        ),
        token_usage=meter.create_histogram(
            semconv.METRIC_USAGE, unit="{token}", description="Tokens per model call"
        ),
        run_duration=meter.create_histogram(
            semconv.METRIC_RUN_DURATION, unit="s", description="Agent run duration"
        ),
        stream_ttft=meter.create_histogram(
            semconv.METRIC_STREAM_TTFT, unit="s", description="Stream time to first token"
        ),
        tool_duration=meter.create_histogram(
            semconv.METRIC_TOOL_DURATION, unit="s", description="Tool call duration"
        ),
        errors=meter.create_counter(
            semconv.METRIC_ERRORS, unit="{error}", description="Failed runs by error code"
        ),
        policy_blocks=meter.create_counter(
            semconv.METRIC_POLICY_BLOCKS, unit="{block}", description="Requests blocked by rule"
        ),
        model_fallbacks=meter.create_counter(
            semconv.METRIC_MODEL_FALLBACKS,
            unit="{fallback}",
            description="Model calls switched to a fallback model",
        ),
        approvals=meter.create_counter(
            semconv.METRIC_APPROVALS,
            unit="{approval}",
            description="Approval requests and decisions",
        ),
        memory_operations=meter.create_counter(
            semconv.METRIC_MEMORY_OPERATIONS,
            unit="{operation}",
            description="Per-user memory operations",
        ),
        checkpoint_duration=meter.create_histogram(
            semconv.METRIC_CHECKPOINT_DURATION, unit="s", description="Checkpointer operation"
        ),
        budget_settle_failures=meter.create_counter(
            semconv.METRIC_BUDGET_SETTLE_FAILURES,
            unit="{failure}",
            description="Token budget settlements the ledger did not accept",
        ),
        service_ready=meter.create_observable_gauge(
            semconv.METRIC_SERVICE_READY,
            callbacks=[_observe_ready],
            description="1 if the latest readiness evaluation passed, 0 if it failed",
        ),
        db_pool_waiting=meter.create_observable_gauge(
            semconv.METRIC_DB_POOL_WAITING,
            callbacks=[_observe_pool_waiting],
            unit="{request}",
            description="Requests waiting for a Postgres pool connection",
        ),
    )


def _instruments() -> _Instruments:
    return _build(_meter())


def _error(error_type: str | None) -> Attributes:
    return {semconv.ERROR_TYPE: error_type} if error_type else {}


def record_model_call(
    seconds: float,
    *,
    provider: str,
    model: str,
    error_type: str | None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> None:
    """One model call's duration and, when the provider reported them, its tokens."""
    instruments = _instruments()
    base = {
        semconv.GEN_AI_OPERATION_NAME: semconv.OPERATION_CHAT,
        semconv.GEN_AI_PROVIDER_NAME: provider,
        semconv.GEN_AI_REQUEST_MODEL: model,
    }
    instruments.operation_duration.record(seconds, {**base, **_error(error_type)})
    for token_type, count in (
        (semconv.USAGE_TYPE_INPUT, input_tokens),
        (semconv.USAGE_TYPE_OUTPUT, output_tokens),
    ):
        if count is not None:
            instruments.token_usage.record(count, {**base, semconv.GEN_AI_USAGE_TYPE: token_type})


def record_run(seconds: float, *, outcome: str, error_type: str | None) -> None:
    """One agent run's duration."""
    _instruments().run_duration.record(
        seconds,
        {
            semconv.GEN_AI_OPERATION_NAME: semconv.OPERATION_INVOKE_AGENT,
            semconv.NEURON_OUTCOME: outcome,
            **_error(error_type),
        },
    )


def record_stream_ttft(seconds: float, *, outcome: str) -> None:
    """A stream's time to its first token, by how the stream ended."""
    _instruments().stream_ttft.record(seconds, {semconv.NEURON_OUTCOME: outcome})


def record_tool_call(seconds: float, *, tool: str, outcome: str, error_type: str | None) -> None:
    """One tool call's duration; `tool` is a registered tool name, never model output."""
    _instruments().tool_duration.record(
        seconds,
        {
            semconv.GEN_AI_OPERATION_NAME: semconv.OPERATION_EXECUTE_TOOL,
            semconv.GEN_AI_TOOL_NAME: tool,
            semconv.NEURON_OUTCOME: outcome,
            **_error(error_type),
        },
    )


def record_error(error_type: str) -> None:
    """Count one failed run or request by its stable `AppError` code."""
    _instruments().errors.add(1, {semconv.ERROR_TYPE: error_type})


def record_policy_block(rule: str) -> None:
    """Count one request or tool call refused by `rule`."""
    _instruments().policy_blocks.add(1, {semconv.NEURON_RULE: rule})


def record_model_fallback(source: str, target: str) -> None:
    """Count one switch from model `source` to model `target` (configured identifiers)."""
    _instruments().model_fallbacks.add(
        1, {semconv.NEURON_FALLBACK_FROM: source, semconv.NEURON_FALLBACK_TO: target}
    )


def record_approval(decision: str) -> None:
    """Count one approval request (`requested`) or decision (`approve`, `reject`)."""
    _instruments().approvals.add(1, {semconv.NEURON_APPROVAL_DECISION: decision})


def record_memory_operation(operation: str, *, outcome: str) -> None:
    """Count one memory operation (`remember`, `list`, `forget`, `erase`)."""
    _instruments().memory_operations.add(
        1, {semconv.NEURON_MEMORY_OPERATION: operation, semconv.NEURON_OUTCOME: outcome}
    )


def record_checkpoint(seconds: float, *, outcome: str, error_type: str | None) -> None:
    """One checkpointer operation's duration."""
    _instruments().checkpoint_duration.record(
        seconds,
        {semconv.NEURON_OUTCOME: outcome, **_error(error_type)},
    )


def record_budget_settle_failure() -> None:
    """Count one settlement that could not be written to the token ledger."""
    _instruments().budget_settle_failures.add(1)


def observe_expired_leases(read: Callable[[], int]) -> None:
    """Report `read()` as the gauge of run leases past `expires_at` (see `semconv`)."""

    def observe(_: CallbackOptions) -> list[Observation]:
        return [Observation(read())]

    _meter().create_observable_gauge(
        semconv.METRIC_RUN_LEASES_EXPIRED,
        callbacks=[observe],
        unit="{lease}",
        description="Run leases past expires_at that are not yet deleted",
    )
