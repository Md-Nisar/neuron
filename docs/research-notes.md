# Research Notes

## Official Documentation Consulted

- LangChain agents: `create_agent` is the current configurable harness for model, tools, prompt, structured output, middleware, and state.
- LangChain structured output: schema types can be passed via `response_format`, and validated data is returned under `structured_response`.
- LangGraph Graph API: `StateGraph`, `START`, `END`, nodes, and explicit edges remain the core graph construction primitives.
- LangGraph persistence: checkpointers are short-term thread state; stores are long-term memory. Agent Server manages persistence when deployed there.
- LangGraph application structure: `langgraph.json` declares dependencies, graphs, and env file.
- LangGraph deployment: LangSmith Cloud/Agent Server is the managed production path; self-hosting is also possible.
- LangSmith evaluation: recommended workflow is dataset creation, evaluators, offline experiments, online monitoring, and feedback loops.

## Repository Patterns Inspected

- `langchain-ai/simple-agent-template`: adopted `uv`, `pyproject.toml`, `langgraph.json`, simple tools, and deployable graph entrypoint. Expanded structure for production boundaries and docs.
- `langchain-ai/langgraph-example-pyproject`: noted as archived; useful only as historical evidence for `pyproject.toml` deployment shape.
- `langchain-ai/open_deep_research`: confirms provider configurability and evaluation emphasis, but its multi-agent/research complexity is not justified here.
- `langchain-ai/react-agent`: useful ReAct template, but this project uses `create_agent` directly inside one graph node.

## Adopted Principles

- Keep graph control flow explicit.
- Keep tools small, deterministic, and testable.
- Separate transport, service, graph, agent, model, tools, settings, security, and observability.
- Avoid retrieval, subgraphs, multi-agent orchestration, and custom durable persistence until requirements demand them.

## v0.5.0 Research: Evaluation and Observability (2026-10)

Input to ADR 0007. Collected 2026-10-15. Several vendor pages (docs.langchain.com,
developers.openai.com, opentelemetry.io, langfuse.com) could not be fetched from the
research environment, so claims about them rest on search excerpts or on the GitHub
source of the spec; treat pricing and licence details as perishable.

### Agent architecture landscape (what it means for neuron)

- Every major agent stack has converged on the same core loop: a model call with
  tool definitions, tool execution, repeat, with middleware/hooks around both
  (LangChain `create_agent` middleware, OpenAI Agents SDK guardrails and tracing
  processors, Google ADK callbacks and plugins, Microsoft Agent Framework
  middleware, Claude Agent SDK hooks). neuron already has this seam:
  `_ToolAuthorizationMiddleware` in `models/factory.py` wraps every model and tool
  call. **Telemetry belongs in that seam**, not in a third-party monkeypatch.
- Every stack also ships tracing as a first-class concern, and the cross-vendor
  convergence point is OpenTelemetry's GenAI semantic conventions (agent spans
  `invoke_agent`/`execute_tool`, inference spans `chat {model}`).
- Anthropic ("Building effective agents") and LangChain both still recommend the
  simplest topology that works. Memory, RAG, planning and multi-agent orchestration
  are product features with their own failure modes; none is needed to measure the
  current agent, so they stay out of v0.5.0 (ADR 0001, 0002) and belong to v0.7.0.
  What v0.5.0 must do is make them *measurable* once they arrive: per-span cost,
  per-tool latency/error metrics and trajectory evals extend to retrieval and
  sub-agents without redesign.

### Evaluation practice

- Anthropic, "Demystifying evals for AI agents" (2026-01):
  https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
  - Vocabulary: task, trial, grader, transcript, outcome. Grade outcomes over rigid
    step sequences.
  - pass@k (any of k trials succeeds) vs **pass^k** (all k succeed). For a
    production agent users need consistency, so pass^k is the reliability metric.
  - Code graders (cheap, reproducible, brittle), model graders (nuanced,
    non-deterministic, must be calibrated against humans), human graders (gold
    standard, used for calibration).
  - Separate **regression** suites (near 100%, gated) from **capability** suites
    (low pass rate, a target, reported). Start with 20-50 tasks from real failures,
    including "should not" cases.
- Anthropic, "Adding error bars to evals" (2024): report the mean with standard
  error / 95% CI and cluster errors for related questions; compare models with
  paired differences. https://arxiv.org/abs/2411.00640
- LangSmith: trajectory evals via `agentevals` (`strict`, `unordered`, `subset`,
  `superset` match), pytest plugin (`@pytest.mark.langsmith`) with a committed
  request cache, online evaluators with sampling, feedback keyed by run id,
  annotation queues. https://docs.langchain.com/langsmith/trajectory-evals,
  https://docs.langchain.com/langsmith/pytest
- Google ADK: eval sets with a trajectory score and a response score, each with a
  threshold; EXACT trajectory matching breaks on harmless extra tool calls.
  https://codelabs.developers.google.com/adk-eval/instructions
- Microsoft Azure AI Evaluation: LLM-judge agent evaluators (intent resolution,
  tool call accuracy, task adherence).
  https://learn.microsoft.com/en-us/azure/ai-foundry/concepts/evaluation-evaluators/agent-evaluators
- UK AISI Inspect AI: Task = dataset + solver + scorer, `epochs` for repeated
  trials. Research-grade; best for deep security evals. https://inspect.aisi.org.uk/
- OpenAI's hosted Evals platform is vendor-specific; search excerpts report it is
  being retired in favour of Promptfoo, but no retirement date could be verified.
  Not considered.
- Judge calibration: label ~100 traces per failure mode, require TPR and TNR >= 0.9
  on a held-out split before a judge gates anything; prefer binary,
  one-dimension-per-judge rubrics with a pinned judge model.
- CI gating: gate deterministic checks and security invariants on every PR; run
  repeated-trial and judge suites nightly or pre-release and *report* them against
  a baseline with confidence intervals; never let infrastructure errors count as
  quality failures.
- Security evals: AgentDojo (https://github.com/ethz-spylab/agentdojo), InjecAgent
  (https://arxiv.org/abs/2403.02691), garak, PyRIT, Promptfoo red-team plugins
  (indirect injection, BOLA/BFLA). Assert on state and allow-lists, never on judge
  opinion.

| Tool | Licence / hosting | Verdict for neuron |
| --- | --- | --- |
| LangSmith | SaaS; self-host Enterprise-only | Keep: already a dependency, native to LangGraph. Optional, never required. |
| Langfuse | MIT core, self-hostable, OTel-native | Best option if self-hosting or data residency is required. |
| Arize Phoenix | Elastic 2.0, self-hostable | Good local trace viewer; weaker for CI gating. |
| Braintrust | SaaS | A second SaaS is not justified. |
| DeepEval / Ragas | Apache-2.0 / OSS | Overlap with our harness; Ragas is RAG-centric. Borrow metric ideas only. |
| Promptfoo | MIT CLI | Best fit for optional red-teaming in CI. |
| Inspect AI | MIT | Occasional deep security runs, not product CI. |
| OpenAI Evals | Hosted, OpenAI-specific | Not considered. |

### Observability practice

- OpenTelemetry GenAI semantic conventions are still **Development** status. In
  core semconv v1.42.0 (2026-06) the `gen_ai.*` names moved to the separate
  `open-telemetry/semantic-conventions-genai` repo, which has no tagged release.
  https://github.com/open-telemetry/semantic-conventions-genai
  - `gen_ai.system` was renamed `gen_ai.provider.name` (v1.37).
  - Inference span: `{gen_ai.operation.name} {gen_ai.request.model}`, kind CLIENT;
    agent operations `invoke_agent` and `execute_tool`; attributes
    `gen_ai.request.model`, `gen_ai.response.model`, `gen_ai.usage.input_tokens`,
    `gen_ai.usage.output_tokens`, cache and reasoning token attributes (v1.40-1.41),
    `gen_ai.tool.name`, `gen_ai.conversation.id`, `error.type`.
  - Metrics on main replace `gen_ai.client.token.usage` with per-kind counters;
    released instrumentations still emit the old histogram.
  - Content capture (`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT`) is off by
    default; `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental` opts in to
    the newest names.
  - Consequence: keep every attribute name in one module and pin it.
- Instrumentation options:
  - LangSmith native tracing has the best LangGraph fidelity and can emit OTel
    (`LANGSMITH_OTEL_ENABLED`), but it sends prompts and answers to a SaaS unless
    `LANGSMITH_HIDE_INPUTS`/`LANGSMITH_HIDE_OUTPUTS` or an anonymizer is set.
  - OpenLLMetry and OpenInference capture content **by default** and use their own
    or older attribute names; running several instrumentors double-counts tokens.
  - `opentelemetry-instrumentation-openai-v2` tracks semconv closely but only sees
    the OpenAI client, not the agent.
  - `opentelemetry-instrumentation-fastapi` gives HTTP RED metrics; the ASGI span
    does not cover a whole SSE stream, so streams need a manual span.
- Backends: Grafana LGTM (Tempo, Loki, Prometheus/Mimir) is fully self-hostable and
  OTLP-native; Langfuse adds an LLM-specific UI over OTLP/HTTP; Datadog and
  Honeycomb accept GenAI semconv over OTLP. With OTLP out of the app, the backend
  is a Collector configuration choice.
- What to measure: HTTP RED; time to first *user-visible* token; tokens by kind and
  estimated cost per model; tool calls, latency and errors; provider errors by
  class; retries; structured-output failures; policy blocks; checkpointer latency.
  Never label metrics by user, owner key, thread or request id; those belong on
  spans and logs. Exemplars link histogram points to traces.
- Multi-worker metrics: `prometheus_client` multiprocess mode loses exemplars and
  custom collectors; the OTel Prometheus exporter does not support multiple
  processes. Pushing OTLP from each worker to a Collector avoids both.
- Privacy: content capture off, allow-list (not block-list) redaction in the
  Collector, tail sampling (keep errors and slow traces) at the Collector, and
  backend retention aligned with the v0.4.0 data-rights story. Trace content is not
  deleted when a thread is deleted, which is the main reason to never put content
  in traces.
- Correlation: a structlog processor adds `trace_id`/`span_id` from the current span;
  W3C `traceparent` is the default propagator.
