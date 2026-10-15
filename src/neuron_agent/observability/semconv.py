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
