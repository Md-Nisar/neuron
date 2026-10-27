# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Every span, metric and attribute name the service emits (ADR 0007, decision 1).

Names follow the OpenTelemetry semantic conventions v1.41.0 and the GenAI conventions, which
have moved to the `semantic-conventions-genai` repository, as of 2026-10; their status is
Development. `gen_ai.usage.input_tokens`/`output_tokens` include the cache-read,
cache-creation and reasoning counts. Upgrading the
conventions is a change to this module only; a test rejects these names anywhere else.
"""

from __future__ import annotations

SEMCONV_VERSION = "1.41.0"

# Resource attributes.
SERVICE_NAME = "service.name"
SERVICE_VERSION = "service.version"
DEPLOYMENT_ENVIRONMENT_NAME = "deployment.environment.name"
SERVICE_INSTANCE_ID = "service.instance.id"

# Service attributes.
NEURON_CORRELATION_ID = "neuron.correlation_id"

# Span names: `{operation} {target}` for GenAI spans, as the conventions require.
AGENT_NAME = "neuron"
OPERATION_INVOKE_AGENT = "invoke_agent"
OPERATION_CHAT = "chat"
OPERATION_EXECUTE_TOOL = "execute_tool"
STREAM_SPAN = "neuron.stream"
# One span per approval request or decision, and one per memory operation (ADR 0009). Names and
# counts only: never the tool arguments, the note text, an ID or an owner key.
APPROVAL_SPAN = "neuron.approval"
MEMORY_SPAN_PREFIX = "neuron.memory"

# GenAI attributes.
GEN_AI_OPERATION_NAME = "gen_ai.operation.name"
GEN_AI_AGENT_NAME = "gen_ai.agent.name"
GEN_AI_CONVERSATION_ID = "gen_ai.conversation.id"
GEN_AI_PROVIDER_NAME = "gen_ai.provider.name"
GEN_AI_REQUEST_MODEL = "gen_ai.request.model"
GEN_AI_RESPONSE_MODEL = "gen_ai.response.model"
GEN_AI_USAGE_INPUT_TOKENS = "gen_ai.usage.input_tokens"
GEN_AI_USAGE_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS = "gen_ai.usage.cache_read.input_tokens"
GEN_AI_USAGE_CACHE_CREATION_INPUT_TOKENS = "gen_ai.usage.cache_creation.input_tokens"
GEN_AI_USAGE_REASONING_OUTPUT_TOKENS = "gen_ai.usage.reasoning.output_tokens"
GEN_AI_TOOL_NAME = "gen_ai.tool.name"
GEN_AI_USAGE_TYPE = "gen_ai.token.type"
USAGE_TYPE_INPUT = "input"
USAGE_TYPE_OUTPUT = "output"
ERROR_TYPE = "error.type"

# Run, model-call, tool-call and stream attributes. Never content, never a full owner key.
NEURON_RUN_ID = "neuron.run_id"
NEURON_OWNER_KEY_PREFIX = "neuron.owner_key_prefix"
NEURON_TURN = "neuron.turn"
NEURON_RETRY_COUNT = "neuron.retry_count"
NEURON_OUTCOME = "neuron.outcome"
NEURON_STREAM_TTFT_MS = "neuron.stream.ttft_ms"
NEURON_STREAM_EVENTS = "neuron.stream.events"
NEURON_STREAM_TERMINATION = "neuron.stream.termination"
NEURON_RULE = "neuron.rule"
NEURON_APPROVAL_DECISION = "neuron.approval.decision"  # requested, approve or reject
NEURON_APPROVAL_ACTIONS = "neuron.approval.actions"
NEURON_MEMORY_OPERATION = "neuron.memory.operation"  # remember, list, forget or erase
NEURON_MEMORY_ITEMS = "neuron.memory.items"
OUTCOME_INTERRUPTED = "interrupted"  # a run or tool call that paused for approval
NEURON_FALLBACK_FROM = "neuron.fallback.from"
NEURON_FALLBACK_TO = "neuron.fallback.to"

# HTTP attributes kept on the FastAPI HTTP metrics; every other one is dropped (ADR 0007).
HTTP_ROUTE = "http.route"
HTTP_RESPONSE_STATUS_CODE = "http.response.status_code"

# Metric names and units. Durations are seconds. Attributes are the allow-list below.
METRIC_OPERATION_DURATION = "gen_ai.client.operation.duration"
METRIC_USAGE = "gen_ai.client.token.usage"
METRIC_RUN_DURATION = "neuron.agent.run.duration"
METRIC_STREAM_TTFT = "neuron.agent.stream.ttft"
METRIC_TOOL_DURATION = "neuron.agent.tool.duration"
METRIC_ERRORS = "neuron.agent.errors"
METRIC_POLICY_BLOCKS = "neuron.agent.policy.blocks"
# Model fallbacks, by the configured model ids switched from and to (bounded, operator-chosen).
METRIC_MODEL_FALLBACKS = "neuron.model.fallbacks"
# Approval requests and decisions by `neuron.approval.decision`; memory operations by
# `neuron.memory.operation` and `neuron.outcome`.
METRIC_APPROVALS = "neuron.approvals"
METRIC_MEMORY_OPERATIONS = "neuron.memory.operations"
METRIC_CHECKPOINT_DURATION = "neuron.checkpoint.duration"
METRIC_SERVICE_READY = "neuron.service.ready"
METRIC_DB_POOL_WAITING = "neuron.db.pool.waiting"
# Run leases past `expires_at` and not yet deleted: a replica died mid-run or a release failed.
# Alert-ready (the rule itself is #155); every replica reports the same table-wide value.
METRIC_RUN_LEASES_EXPIRED = "neuron.run_leases.expired"
# Token-budget settlements the ledger did not accept (#147). The run's answer was delivered; the
# owner's next admission fails closed until the write is retried and succeeds. No attributes.
METRIC_BUDGET_SETTLE_FAILURES = "neuron.token_budget.settle_failures"
METRIC_HTTP_REQUEST_DURATION = "http.server.request.duration"
METRIC_HTTP_REQUEST_BODY_SIZE = "http.server.request.body.size"
METRIC_HTTP_RESPONSE_BODY_SIZE = "http.server.response.body.size"
METRIC_HTTP_ACTIVE_REQUESTS = "http.server.active_requests"

# The only attribute keys a metric may carry. Users, owner keys, threads, runs and requests
# never label a metric: each would create one time series per value.
METRIC_ATTRIBUTE_ALLOW_LIST = frozenset(
    {
        GEN_AI_REQUEST_MODEL,
        GEN_AI_PROVIDER_NAME,
        GEN_AI_OPERATION_NAME,
        GEN_AI_TOOL_NAME,
        GEN_AI_USAGE_TYPE,
        ERROR_TYPE,
        HTTP_ROUTE,
        HTTP_RESPONSE_STATUS_CODE,
        NEURON_OUTCOME,
        NEURON_RULE,
        NEURON_FALLBACK_FROM,
        NEURON_FALLBACK_TO,
        NEURON_APPROVAL_DECISION,
        NEURON_MEMORY_OPERATION,
    }
)
