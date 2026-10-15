# ADR 0007: Evaluation and Observability

## Status

Proposed (v0.5.0).

## Problem

v0.4.0 can say who called the agent and what they may do, but not how well the
agent answers or how it behaves in production:

- Model-facing behaviour has only ever been verified with fake models. The live
  suites became runnable after v0.4.0, and their first runs found four defects.
- The `neuron-eval` report is a single pass/fail per case: no repeated trials, no
  confidence intervals, no latency, tokens or cost, no baseline to compare with.
  Since #83, CI selects `tests/evals` but the default
  `-m 'not integration and not eval'` deselects every eval test, so CI runs no
  evals (being fixed separately).
- Production telemetry is structlog JSON only. There are no metrics, no traces, no
  SLOs and no dashboards. Token usage is logged as one total; cost is unknown.
- `APP_ENABLE_LANGSMITH` exists but is never read. LangSmith tracing is controlled
  only by `LANGSMITH_TRACING`, which, when set, sends prompts and answers to a SaaS
  regardless of environment.
- `agent_request_validation_failed` logs Pydantic's `exc.errors()`, whose entries
  carry the rejected `input` value, so request text can reach logs (being fixed
  separately).
- The Agent Server path never calls `configure_logging`, carries no `request_id` or
  `run_id`, and does not count tokens.

## Requirements

- Measure answer quality, tool-use correctness, reliability across repeated trials
  and security invariants, on fake models in CI and on real models before release.
- Compare a candidate against a recorded baseline with stated uncertainty; gate
  only on checks that are deterministic or calibrated.
- Expose latency, errors, tokens, estimated cost and tool behaviour as metrics, and
  every run as a trace, without coupling the code to one vendor.
- Never put prompts, answers, tool arguments, raw identities or tokens in telemetry
  (SECURITY.md, ADR 0006). Identity appears only as the existing 12-character owner
  key prefix, and never as a metric label.
- Telemetry is off or no-op by default; tests and local development need no
  collector, SaaS account or network.
- Apply the same telemetry to the FastAPI and Agent Server paths.
- Add no queues, retrieval, custom stores or multi-agent orchestration (ADR 0001).

## Options Considered

### Telemetry standard

1. **LangSmith only.** Best LangGraph fidelity, already a dependency. But SaaS,
   self-hosting is Enterprise-only, no metrics, and content goes out by default.
2. **Third-party auto-instrumentation** (OpenLLMetry, OpenInference). Broad and
   quick, but they capture content by default, use non-standard or older attribute
   names, and double-count tokens when combined.
3. **OpenTelemetry SDK with spans and metrics emitted from our own middleware.**
   Vendor-neutral (OTLP to any backend), content-free by construction, and uses the
   seam that already wraps every model and tool call. Costs us a small amount of
   code and tracking a spec that is still in Development.

Chosen: **3**, with LangSmith kept as an optional, opt-in tracing and experiment
backend.

### Metrics transport

1. `prometheus_client` with a `/metrics` endpoint: simple, but multiprocess mode
   loses exemplars and needs a shared directory; another unauthenticated endpoint.
2. OTel metrics with the Prometheus exporter: unsupported with multiple workers.
3. **OTel metrics pushed over OTLP to a Collector**, which exposes them to
   Prometheus/Mimir or any vendor.

Chosen: **3**.

### Evaluation framework

LangSmith experiments, Langfuse, Braintrust, DeepEval, Inspect AI, Promptfoo and
OpenAI Evals were compared (`docs/research-notes.md`). The existing pytest +
`neuron-eval` harness already runs cases through `AgentService` with real
authorization; replacing it buys little. OpenAI's hosted Evals is a
vendor-specific service and is not considered.

Chosen: **extend the in-repo harness**, with optional upload of results to
LangSmith experiments. Promptfoo red-teaming and Inspect/AgentDojo stay optional
tools, not dependencies.

## Decisions

### 1. Instrumentation

- `observability/telemetry.py` configures the OTel SDK (traces and metrics) from
  `Settings`. With `APP_OTEL_ENABLED=false` (the default) the global no-op providers
  are used and nothing is exported.
- `observability/semconv.py` holds every span, metric and attribute name, pinned to
  the GenAI conventions as of semconv v1.41 / `semantic-conventions-genai` main,
  2026-10. Upgrading the conventions is a one-file change with a test.
- Spans:
  - HTTP server spans from `opentelemetry-instrumentation-fastapi`, excluding
    `/health/*`.
  - `invoke_agent neuron` (INTERNAL) around each run, opened in `AgentService` and
    in the graph node on Agent Server, with `gen_ai.conversation.id` (thread id),
    `neuron.run_id`, `neuron.owner_key_prefix` and `neuron.turn`.
  - `chat {model}` (CLIENT) per model call and `execute_tool {tool}` per tool call,
    both from the existing agent middleware, with model/provider, token usage by
    kind, `gen_ai.tool.name`, retry count and `error.type` set to our `AppError`
    code.
  - `neuron.stream` around an SSE stream, recording time to first visible token and
    termination reason, because the ASGI span does not cover the stream body.
- No third-party LangChain/OpenAI instrumentor is installed, so there is one source
  of token counts.
- Content attributes (`gen_ai.input.messages`, `gen_ai.output.messages`,
  `gen_ai.system_instructions`, tool arguments and results) are never set. There is
  no setting to enable them in v0.5.0.

### 2. Metrics

Instruments (names from `semconv.py`): `gen_ai.client.operation.duration`,
`gen_ai.client.token.usage` (by `gen_ai.token.type`, the name released backends
understand), `neuron.agent.run.duration`, `neuron.agent.stream.ttft`,
`neuron.agent.tool.duration`, `neuron.agent.cost` (estimated USD),
`neuron.agent.errors` (by `error.type`), `neuron.agent.policy.blocks` (by rule) and
`neuron.checkpoint.duration`, plus the FastAPI HTTP metrics.

Labels are an allow-list enforced by a test: `gen_ai.request.model`,
`gen_ai.provider.name`, `gen_ai.operation.name`, `gen_ai.tool.name`,
`gen_ai.token.type`, `error.type`, `http.route`, `http.response.status_code`,
`neuron.outcome`, `neuron.rule`. Users, owner keys, threads, runs and requests never
label a metric.

### 3. Logs and correlation

- A structlog processor adds `trace_id` and `span_id` when a valid span is current.
- `X-Correlation-ID` stays the request's correlation ID; the service-minted
  `request_id` is kept, and both are recorded on the run span.
- The graph module configures logging when it is loaded by Agent Server.

### 4. Tokens and cost

- Usage is recorded by kind (input, output, cache read, reasoning) per model call,
  not only as a total. Budgets keep charging totals (ADR 0006 is unchanged).
- Optional in v0.5.0 (may slip without blocking the release): estimated cost from a versioned pricing file
  (`config/model_pricing.json`: per-model USD per million tokens by kind, with an
  `as_of` date). Unknown models report tokens but no cost and log
  `model_pricing_missing` once. Cost is an estimate for trends, not billing.

### 5. LangSmith governance

`APP_ENABLE_LANGSMITH` becomes the single switch. Settings sets
`LANGSMITH_TRACING` from it, and outside `development` it also requires
`APP_LANGSMITH_CONTENT_APPROVED=true`; otherwise inputs and outputs are hidden
(`LANGSMITH_HIDE_INPUTS`/`LANGSMITH_HIDE_OUTPUTS`). A shell-level
`LANGSMITH_TRACING=true` without the app switch is overridden and logged at
startup. On Agent Server, the platform's own tracing is out of scope for this
switch and is documented as such.

### 6. Evaluation

Three suites, one harness:

| Suite | Data | Graders | Runs | Gate |
| --- | --- | --- | --- | --- |
| Regression | v1-v2 cases plus cases from fixed defects | Code: schema, tool trajectory, structured expectations, keywords only where unavoidable, refusals | Every PR (fake model), nightly and pre-release (live) | Fake: 100%. Live: per case (below). |
| Security | v3 plus v4 injection cases | Code: state, allow-list and isolation invariants | Every PR (fake), nightly and pre-release (live) | pass^k = 100% |
| Quality | Rubric cases | LLM judge, binary, one dimension per judge, pinned judge model | Deferred beyond v0.5.0 | Reported only, until the judge is calibrated (TPR, TNR >= 0.9 on >= 100 labelled runs) |

- **Trials:** `neuron-eval --trials k` runs each case k times and reports pass rate,
  pass^k, and a 95% Wilson interval per suite and category.
- **Trajectory:** expected tools are matched in `unordered` mode by default;
  `subset` (no tool outside the expected set) is available per case. Every case
  also asserts no tool outside the caller's permissions ran.
- **Report:** a versioned JSON schema adding latency (p50/p95), tokens by kind and
  estimated cost per case and suite, model, git SHA and dataset versions.
- **Live regression gate (per case):** a regression case that passed every trial in
  the baseline must not fail every trial in the candidate. A suite-level confidence
  interval is too wide to gate on at current sizes (16 cases × 3 trials at ~0.8
  pass gives a 95% Wilson interval of ~0.67-0.89, so losing two cases looks like
  noise). Suite intervals are reported, not gated, until a gated suite has about
  50 cases.
- **Baselines:** `evals/baselines/<model>.json` is committed;
  `neuron-eval compare` applies the per-case and security gates, and reports
  infrastructure errors (provider/quota/timeout) separately; they make a run
  inconclusive, never a pass or a quality failure.
- **Models:** the development baseline is the NVIDIA catalog model
  `nvidia/nemotron-3-super-120b-a12b` (live on `main` at `da1492e`: single-turn
  14/16, multi-turn 11/13, security 12/12), run nightly in CI with an NVIDIA
  free-tier key limited to 40 requests per minute. The eval runner throttles its
  model calls below that limit, and a provider 429 makes the run inconclusive,
  not a quality failure. Automated runs are allowed but must comply with
  NVIDIA's applicable API terms, rate limits and usage restrictions; the workflow
  stays at one scheduled run a night plus manual runs. The release gate must
  eventually run on the production model (OpenAI); until a funded key exists, a
  release that cannot do so lists it as a known issue.
- **Cost of a run:** one live pass of all suites takes about 20 minutes, so the
  nightly 3-trial run takes about an hour.
- **CI:** a PR job runs the eval-marked fake-model suites (fixing the current
  deselection). A scheduled and manually-triggered workflow runs the live suites
  when a provider secret is configured; it uploads the report as an artifact and,
  with `APP_ENABLE_LANGSMITH`, as a LangSmith experiment.

### 7. Production feedback (deferred to v0.8.0)

A run-scoped feedback endpoint is useful only with a UI, so it moves to v0.8.0.
The intended shape, for that release: `POST
/v1/threads/{thread_id}/runs/{run_id}/feedback` (`{score: -1|1, reason?}`),
owner-checked like other thread routes, a new `feedback:write` scope, recorded as a
span event, a `user_feedback` log event (fixed reason codes, no free text) and a
metric, and forwarded to LangSmith feedback when enabled.

### 8. SLOs, alerts and readiness

- SLIs and initial SLO targets (availability excluding 4xx, p95 time to first
  token, p95 run duration, provider error rate) and multi-window burn-rate alerts
  are defined in `OPERATIONS.md`; targets are set from live data at the release
  gate.
- `deploy/observability/` ships a Collector configuration (memory limiter,
  allow-list attribute redaction, tail sampling that keeps errors and slow traces,
  batch) and example alert rules. A development-only Compose stack with Grafana,
  Tempo, Loki, Prometheus and dashboards is optional.
- `/health/ready` probes JWKS reachability (closing the v0.4.0 known issue); it
  still makes no model call.

## Migration and rollout

- Defaults change nothing: OTel off, LangSmith off, no new required settings.
- Breaking: a shell `LANGSMITH_TRACING=true` no longer enables tracing on its own;
  set `APP_ENABLE_LANGSMITH=true`.
- New dependencies: `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http`,
  `opentelemetry-instrumentation-fastapi`. Collector and Grafana are deployment
  artefacts, not Python dependencies.

## Non-goals (v0.5.0)

- Capturing prompt or answer content in any telemetry backend.
- LLM-judge quality evals (deferred; report-only even when built) and the user
  feedback endpoint (v0.8.0).
- Online LLM-judge scoring of production traffic (it needs content to leave the
  service; revisit with an anonymiser and explicit consent).
- A feedback or eval-results database, dashboards UI in the app, billing-grade cost.
- Rate limits, budgets and the input policy on Agent Server (v0.4.0 known issue,
  tracked separately).
- Retrieval, memory, planning or multi-agent evaluation; the span and trajectory
  model extends to them when they exist (v0.7.0).

## Consequences

- Every run is traceable and measurable through a vendor-neutral pipeline; the
  backend is a Collector configuration choice.
- We own a small amount of instrumentation code and must update `semconv.py` as the
  GenAI conventions stabilise.
- Releases are gated on live, repeated-trial evidence rather than fake-model
  passes, which needs a funded provider key in CI.
- Gating is per case and on deterministic checks only; suite-level statistics are
  informational until the gated suites grow.

## References

- `docs/research-notes.md`, "v0.5.0 Research: Evaluation and Observability".
- https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
- https://arxiv.org/abs/2411.00640
- https://github.com/open-telemetry/semantic-conventions-genai
- https://docs.langchain.com/langsmith/trajectory-evals
- https://docs.langchain.com/langsmith/mask-inputs-outputs
