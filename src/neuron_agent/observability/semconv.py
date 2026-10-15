"""Every span, metric and attribute name the service emits (ADR 0007, decision 1).

Names follow the OpenTelemetry semantic conventions v1.41.0 and the GenAI conventions in
`semantic-conventions-genai` as of 2026-10, whose status is Development. Upgrading the
conventions is a change to this module only; a test rejects these names anywhere else.
"""

from __future__ import annotations

SEMCONV_VERSION = "1.41.0"

# Resource attributes.
SERVICE_NAME = "service.name"
SERVICE_VERSION = "service.version"
DEPLOYMENT_ENVIRONMENT_NAME = "deployment.environment.name"

# Service attributes.
NEURON_CORRELATION_ID = "neuron.correlation_id"

# Span names: `{operation} {target}` for GenAI spans, as the conventions require.
AGENT_NAME = "neuron"
OPERATION_INVOKE_AGENT = "invoke_agent"
OPERATION_CHAT = "chat"
OPERATION_EXECUTE_TOOL = "execute_tool"
STREAM_SPAN = "neuron.stream"

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
GEN_AI_USAGE_REASONING_OUTPUT_TOKENS = "gen_ai.usage.reasoning.output_tokens"
GEN_AI_TOOL_NAME = "gen_ai.tool.name"
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
