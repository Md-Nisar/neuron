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

## v0.6.0 Research: Production Deployment (2026-10)

Input to ADR 0008. Collected 2026-10-19. Primary pages were fetched from
docs.github.com, render.com/docs, docs.fly.io, docs.cloud.google.com,
learn.microsoft.com, docs.aws.amazon.com, docs.langchain.com, langchain.com/pricing,
postgresql.org, pgbouncer.org, psycopg.org, neon.com/docs, docs.docker.com,
kubernetes.io, fastapi.tiangolo.com, sre.google and redis.io, plus the
`langgraph-checkpoint-postgres` 3.1.2 (locked) and 3.2.0 wheels. These rest on search
excerpts or secondary sources only, so treat them as unverified:

- Render's 100-minute HTTP request limit (staff forum posts, not the docs) and the
  third-party summary of Render's July 2026 price list.
- Cloud Run, Railway, Neon and managed-Kubernetes pricing; ECS `stopTimeout` and the
  ALB idle timeout.
- Plan availability of GitHub artifact attestations and the SLSA level claims,
  immutable releases, the 2025 SHA-pinning policy, and how Dependabot updates SHA pins.
- The details of the 2026-03 Trivy compromise (Aqua and Snyk write-ups).
- Whether LangChain's free "Self-Hosted Lite" tier still exists.

www.uvicorn.org could not be fetched at all (DNS failure); its settings were read from
`encode/uvicorn` `docs/*.md` on GitHub. Prices are list prices seen on 2026-10-19 and
are perishable.

### Deployment targets (what it means for neuron)

Limits that matter for `/v1/agent/stream`, `APP_RUN_TIMEOUT_SECONDS=120` and
`APP_STREAM_HEARTBEAT_SECONDS=15`:

| Platform | Request / stream limit | SIGTERM to SIGKILL | Migration hook | Source |
| --- | --- | --- | --- | --- |
| Render | 100 min (forum only) | 30 s default `maxShutdownDelaySeconds`, max 300 s | pre-deploy command (paid instances, 30 min timeout) | https://render.com/docs/deploys |
| Fly.io | none documented; 60 s proxy idle (forum) | `kill_timeout` 5 s default, max 300 s; default signal SIGINT | `release_command` | https://docs.fly.io/reference/configuration |
| Cloud Run | 300 s default, up to 3600 s | **10 s, fixed** | Cloud Run Job | https://docs.cloud.google.com/run/docs/container-contract |
| Azure Container Apps | **240 s** ingress request timeout | n/a | n/a | https://learn.microsoft.com/en-us/azure/container-apps/ingress-overview |
| Kubernetes | set by the ingress | `terminationGracePeriodSeconds` 30 s default | Job / Helm hook | https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/ |

- **Render.** Zero-downtime deploys replace one instance at a time and cancel the
  deploy if a new instance fails its health check; a persistent disk disables them.
  The pre-deploy command runs on the new version before it takes traffic, which suits
  migrations. All paid Render Postgres plans get point-in-time recovery: 3 days on
  Hobby workspaces, 7 days on Pro and above (https://render.com/docs/postgresql-refresh).
  Prices (secondary): Starter web service $7/month (512 MB, 0.5 CPU); Postgres from $6
  (Basic-256mb) or $19 (Basic-1gb), plus $0.30/GB. Two small replicas plus Postgres
  come to about $35/month.
- **Fly.io** has the same shape (bluegreen or rolling deploys, `release_command`,
  managed Postgres with HA from $38/month; PITR window not stated:
  https://docs.fly.io/mpg).
- **Cloud Run** is cheapest at near-zero traffic, but its fixed 10 s shutdown window is
  shorter than a run, so every deploy or scale-in kills in-flight `invoke` runs.
- **Azure Container Apps** (240 s cap) and **AWS App Runner** (closed to new customers:
  https://docs.aws.amazon.com/apprunner/latest/dg/apprunner-availability-change.html)
  are ruled out.
- **Kubernetes** adds preStop hooks, PDBs and CronJobs, and the most operational load
  (upgrades, ingress, cert-manager, secrets). It only makes sense if the target
  organisation already runs a cluster. Control planes cost about $73/month on EKS
  (secondary).
- **Grace must cover the longest run.** Set the platform grace above
  `APP_RUN_TIMEOUT_SECONDS` plus a margin (Render `maxShutdownDelaySeconds: 150`),
  otherwise in-flight `invoke` calls die at SIGKILL. Streams already end within 2 s.

**Render addendum (2026-10-20, ADR 0008 review).** Fetched from render.com/docs:

- **Deploy hooks** take an `imgURL` query parameter "to deploy a specific tag or
  digest"; the rest of the URL must match the service's default image. "Your deploy
  hook URL is a secret!" (one per service, regenerable).
  https://render.com/docs/deploy-hooks
- Not stated anywhere fetched: whether a hook deploy of a prebuilt image runs the
  pre-deploy command, and whether a rollback re-runs it. The deploys page says only
  that pre-deploy "is available for paid web services, private services, and
  background workers" (https://render.com/docs/deploys). ADR 0008 open question 4.
- **Cron jobs** are billed per second of runtime with "a minimum monthly charge of $1
  per cron job service" (https://render.com/docs/cronjobs).
- **Private services** are "just like web services" except unreachable from the
  internet; no separate price was found (assumed web-service instance prices)
  (https://render.com/docs/private-services). render.com/pricing did not render its
  price tables when fetched, so the Starter and Postgres prices above remain the
  secondary source.
- Full topology from these figures (perishable): production 2 × $7 web + $19
  Basic-1gb + about $1 cron + $7 Collector ≈ $42; staging $7 + $6 Basic-256mb + about
  $1 cron (+ $7 if it has its own Collector) ≈ $14-21; storage at $0.30/GB, the
  workspace plan and the telemetry backend are extra.

**LangGraph Agent Server / LangSmith Deployment**
(https://docs.langchain.com/langsmith/agent-server,
https://docs.langchain.com/langsmith/deploy-standalone-server,
https://www.langchain.com/pricing):

- It runs runs from a Postgres-backed queue that allows at most one run per thread,
  re-queues runs from crashed workers, and offers `checkpointer.ttl` retention in
  `langgraph.json`. Redis carries cancellation and stream pub/sub.
- `langgraph-api` is Elastic-2.0 (PyPI metadata); the libraries neuron uses
  (`langgraph`, `langgraph-checkpoint-postgres`) are MIT. A standalone server needs a
  licence key and egress to `beacon.langchain.com`. Self-hosting is Enterprise-only;
  LangSmith Plus ($39/seat/month) includes one small Serverless deployment.
- `langgraph dev` / `langgraph up` are not for production (staff answer:
  https://forum.langchain.com/t/best-practices-for-self-hosting-langgraph-server-oss-without-langgraph-keys/3779).
- For a cost-sensitive single maintainer the self-hosted FastAPI path stays primary;
  Agent Server stays a supported second path.

### CI/CD for the container

- **GHCR.** Publishing with `GITHUB_TOKEN` links the package to the repository; a new
  package is private by default. Add the `org.opencontainers.image.source` label.
  https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry
- **Provenance and SBOM.** `docker/build-push-action` adds `mode=max` provenance by
  default on public repositories; `sbom: true` adds an SBOM attestation. Attestations
  need a push (`load: true` drops them), and max provenance can expose build
  arguments, so secrets go in secret mounts.
  https://docs.docker.com/build/ci/github-actions/attestations/
- **Artifact attestations** (`actions/attest`) need `id-token: write`,
  `attestations: write` and `packages: write`; verify with
  `gh attestation verify oci://IMAGE -R OWNER/REPO`. Public repositories sign with the
  public Sigstore instance. Inline attestations meet SLSA Build L2; a reusable build
  workflow reaches L3 (search excerpts).
  https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations
- **Scanning.** Trivy and Grype are both standard. On 2026-03-19 the
  `aquasecurity/trivy-action` and `setup-trivy` tags were force-pushed to
  credential-stealing commits (all but one tag), and Trivy images 0.69.4-0.69.6 were
  affected (search excerpts:
  https://www.aquasec.com/blog/trivy-supply-chain-attack-what-you-need-to-know). It was
  the second large tag-moving incident after `tj-actions/changed-files` (2025-03): pin
  every action, scanners included, by full commit SHA.
- **Pinning policy.** Since 2025-08-15 the allowed-actions policy can require full SHA
  pins (https://github.blog/changelog/2025-08-15-github-actions-policy-now-supports-blocking-and-sha-pinning-actions/);
  immutable releases lock tags and assets
  (https://github.blog/changelog/2025-10-28-immutable-releases-are-now-generally-available/).
- **Environments.** Up to 6 required reviewers, an option to prevent self-review, tag
  and branch deployment rules, and environment secrets released only after approval.
  On Free/Pro/Team plans required reviewers work only in public repositories; neuron
  is public. https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments
- **Promotion and rollback.** Deploy by digest, promote the same digest from staging to
  production, and keep the previous digest for rollback. Schema changes must be
  expand/contract so the previous image still runs.
- **Migrations.** LangGraph recommends "running migrations as a dedicated deployment
  step" (https://docs.langchain.com/oss/python/langgraph/add-memory).
  `CREATE INDEX CONCURRENTLY` cannot run in a transaction block, and a failed build
  leaves an `INVALID` index that must be dropped and rebuilt
  (https://www.postgresql.org/docs/current/sql-createindex.html); `IF NOT EXISTS`
  then skips it silently.
- **Dependency automation.** Dependabot supports `uv` (GA 2025-03-13) and
  `github-actions`, with `groups` and a `cooldown`
  (https://docs.github.com/en/code-security/dependabot/working-with-dependabot/dependabot-options-reference).
  It updates SHA-pinned actions that carry a `# vX.Y.Z` comment (secondary sources).

Current state: GitHub-owned actions (`actions/checkout@v5`, `setup-python@v6`,
`upload-artifact@v4`, `codeql-action/*@v3`, `dependency-review-action@v4`) are
tag-pinned, there is no `.github/dependabot.yml`, and no workflow builds the image.
The `Dockerfile` falls back to an unlocked resolve (`uv sync --no-dev --frozen || uv
sync --no-dev`), pins neither base image by digest, and `.dockerignore` excludes only
`.env` and `.dev/`.

### Horizontal scaling

- **One Uvicorn process per container**, replicated by the platform; `--workers` only
  on a single host, exec-form `CMD` for signals and lifespan
  (https://fastapi.tiangolo.com/deployment/docker/).
- **Shutdown knobs** (`encode/uvicorn` `docs/settings.md`): without
  `--timeout-graceful-shutdown` Uvicorn waits for every response;
  `--timeout-keep-alive` (5 s default) must stay below the load balancer's idle
  timeout. The installed `sse-starlette` 3.3.4 detects Uvicorn's exit flag, so streams
  end with `service_shutting_down` within 2 s.
- **Probes.** Backend checks belong in readiness, not liveness ("incorrect
  implementation of liveness probes can lead to cascading failures":
  https://kubernetes.io/docs/concepts/configuration/liveness-readiness-startup-probes/),
  which matches `/health/live` and `/health/ready`.
- **Shared limits.** Options are Redis (one atomic Lua script per check:
  https://redis.io/learn/howtos/ratelimiting; a second stateful service with its own
  fail-open/fail-closed decision) or Postgres, which neuron already requires for
  durability:
  - A token bucket is one atomic `UPDATE … RETURNING` per request on a per-key row.
    `UNLOGGED` tables skip WAL but are "automatically truncated after a crash or unclean
    shutdown" and "not replicated to standby servers"
    (https://www.postgresql.org/docs/current/sql-createtable.html). Truncation is
    acceptable for request rates (a crash grants a burst) but not for a token budget,
    which stays logged.
  - It puts a database write in front of every request; a Postgres rate-limit library
    reports about 6.7k requests/s on one node (secondary), far above neuron's needs.
- **Run leases.** Session-level advisory locks are held until unlock or session end
  (https://www.postgresql.org/docs/current/explicit-locking.html), so one held for a
  run pins a pooled connection for the whole run, and PgBouncer-style transaction
  pooling does not support them (https://www.pgbouncer.org/features.html,
  https://neon.com/docs/connect/connection-pooling). Transaction-level advisory locks
  release at commit and are pooler-safe. The pooler-safe lease is a **row with an
  expiry**, claimed with a conditional insert and deleted on release; expiry handles a
  crashed replica. For neuron the lease is a UX and cost guard (turns commit only on
  success), not a correctness lock, so expiry without fencing tokens is acceptable
  (Redis's own page warns failover breaks lock mutual exclusion:
  https://redis.io/docs/latest/develop/clients/patterns/distributed-locks/).
- **JWKS per replica.** Each replica caches keys independently; N replicas cause about
  N fetches per `APP_AUTH_JWKS_CACHE_SECONDS`, which is negligible.

### Operations

- **Secrets.** Platform stores first (Render env groups); GitHub environment secrets
  only for the deploy job; SOPS and Vault/OpenBao are too heavy for one maintainer.
- **Point-in-time recovery** (2026-10): Render 3 days (Hobby workspace) or 7 days (Pro
  and above) on paid plans; Neon 6 h free, up to 7 d on Launch
  (https://neon.com/docs/postgres/backup-restore/history-window); AWS RDS up to 35 d.
- **Restores, not backups.** "No one really wants to make backups; what people really
  want are restores"; test recovery continuously
  (https://sre.google/sre-book/data-integrity/). Every alert needs a playbook entry
  (https://sre.google/workbook/on-call/).

### LangGraph specifics in production

- `setup()` applies `MIGRATIONS` in order and records them in `checkpoint_migrations`;
  three steps are `CREATE INDEX CONCURRENTLY`, as is neuron's own
  `neuron_checkpoints_owner_idx`. Setup therefore needs an autocommit connection and
  should run on a direct (non-pooled) connection, once per deploy, not from every
  replica at start-up.
- **Pooling** (https://www.psycopg.org/psycopg3/docs/advanced/pool.html): keep pools
  small and monitor `get_stats()`. neuron passes `prepare_threshold=0`; behind
  PgBouncer that needs version 1.22+ with `max_prepared_statements` > 0
  (https://www.psycopg.org/psycopg3/docs/advanced/prepare.html). Budget connections as
  replicas × `APP_POSTGRES_POOL_MAX_SIZE`, plus the migration and prune jobs.
- `checkpoint_blobs` grows fastest, and every super-step writes a checkpoint.
  `langgraph-checkpoint-postgres` 3.2.0 (published 2026-10-14) adds
  `aprune(thread_ids, strategy="keep_latest"|"delete")` with no schema change; neuron
  locks 3.1.2. Today's retention deletes whole stale threads, which is enough for
  v0.6.0.

## v0.7.0 Research: Extensible Agent Platform (2026-10)

Input to the v0.7.0 ADRs. Collected 2026-10-27. The roadmap theme is "Tools + models +
HITL + memory". Sources are the LangChain/LangGraph/MCP/OWASP pages named below, a
spike run against the versions in `uv.lock` (`langchain` 1.3.18, `langgraph` 1.2.11,
`langchain-core` 1.6.1), and this repository. Where a page was read through a model
summary, or not at all, the entry says so. Treat vendor docs as perishable: several
pages describe `langchain` >= 1.4.6, which this repository does not lock.

### What v0.7.0 inherits

- Deferred to v0.7.0 by earlier ADRs and drafts: long-term memory and retrieval
  (ADR 0001, 0002), human approval before any mutating tool (ADR 0003), estimated cost
  (`neuron.agent.cost`; no verifiable dated price data yet), and the invalid-`AgentAnswer`
  retry loop that runs until `run_timeout` (`docs/releases/v0.6.0-issues.md`, Deferred).
- CLAUDE.md requires a concrete product requirement and an ADR before memory,
  retrieval, queues or subgraphs. **No product requirement for memory or approvals is
  written down yet.** That is the first decision for the owner, and it decides the scope.
- Production is out of scope until after v1.0.0 (owner decision, 2026-10-27): v0.7.0 is
  built and verified locally; production settings stay, but are not exercised.

### Human approval (HITL)

Sources: https://docs.langchain.com/oss/python/langchain/human-in-the-loop,
https://docs.langchain.com/oss/python/langgraph/interrupts (both read as `.md`).

- `HumanInTheLoopMiddleware(interrupt_on={tool: True | False | {allowed_decisions,
  description, when}})`. Decisions: `approve`, `edit` (same tool name, new args),
  `reject` (optional message), `respond` (required message). Resume is
  `Command(resume={"decisions": [...]})` in the order of the requested actions, on the
  same `thread_id`. A checkpointer is required; the docs name `InMemorySaver` as
  prototype-only.
- **Resume re-runs the interrupted node from its start.** Code before the interrupt
  runs again, so side effects before it must be idempotent or moved after it. The docs
  warn that `respond` is recorded as a *successful* tool result, so it must never stand
  in for denying a side-effecting tool, and that large `edit`s can make the model
  re-plan.
- `interrupt_mode="per_call"` (one interrupt per gated call, answered by interrupt id)
  and `version="v2"`/`stream_events(version="v3")` need `langchain` >= 1.4.6. This
  repository locks 1.3.18, which has only the batched mode. `when` needs >= 1.3.3.
- Not covered by the docs: an agent compiled with `checkpointer=False`, and interrupts
  from a subgraph agent that is only called inside a parent node.
- **Spike (this repository's shape).** `create_agent(..., checkpointer=False)` called
  with `await agent.ainvoke(...)` from a node of a parent graph that has a checkpointer,
  one gated tool, fake model. Result: with `checkpointer=False` the interrupt is raised
  and the resume completes, but **the approved tool never ran** (0 calls) and the run
  still ended normally. With `checkpointer=None` (inherit the parent's) the interrupt
  is raised, and after `approve` the tool ran exactly once. So `models/factory.py`'s
  `checkpointer=False` (ADR 0005) cannot coexist with approvals, and a failure here is
  silent. Any approval feature needs a test that asserts the tool ran once after
  approval and zero times after rejection.
- Consequences to design before building: (1) the agent's internal tool-call state
  would then be checkpointed, which ADR 0005 deliberately avoided (thread history is
  user turns and final answers only); (2) `call_agent` re-runs on resume, so anything it
  does before the agent call (token accounting, audit events, logs) happens twice;
  (3) a pending approval outlives `APP_RUN_TIMEOUT_SECONDS`, so the run must end at the
  pause (release the lease, settle tokens) and the decision must start a new run with
  its own lease, budget and timeout; (4) pending approvals need an owner check (a
  foreign or missing thread is the same 404), a scope (for example `agent:approve`), an
  expiry and retention, and audit events for requested and decided; (5)
  `models/factory.py` already treats `GraphBubbleUp` as "interrupted" in the tool span,
  so tracing has a seam; (6) the streaming route and `StreamLeakGuard` need an
  `interrupt` event.
- `edit` and `respond` widen the attack surface (the human approves one thing, the tool
  runs another). The smallest safe first release allows `approve` and `reject` only.

### Models and providers

Sources: https://docs.langchain.com/oss/python/langchain/middleware/built-in,
https://docs.langchain.com/oss/python/langchain/models (the second was read only in
part; its structured-output and usage sections came through a summary).

- `ModelFallbackMiddleware(first_model, *additional_models)`. Read from the installed
  1.3.18 source: it tries each model in order, catches any `Exception` except
  `GraphBubbleUp`, and re-raises the last one if all fail. The docs do not say how it
  interacts with a retry middleware. neuron's own `provider_retry_middleware` and
  `empty_reply_retry_middleware` sit around the model call, so the order matters and
  needs a test.
- `langchain-core` 1.6.1 has provider-neutral exceptions (`ModelRateLimitError`,
  `ModelAuthenticationError`, `ModelNotFoundError`, `ModelPermissionDeniedError`,
  `ModelTimeoutError`, `ModelAPIError`, `ContextOverflowError`, ...). The models page
  says integrations raise them with an `is_retryable` flag; that was **not** confirmed
  verbatim. Today `classify_agent_error` matches `openai.*` classes only, so a second
  provider would fall through to `AgentExecutionError`. Moving to the neutral types is
  the main code change for multi-provider support.
- Provider packages: `langchain-anthropic` (`ChatAnthropic`) and
  `langchain-google-genai` (`ChatGoogleGenerativeAI`), or `init_chat_model("provider:model")`.
  None is installed or locked. Each is a new dependency (the `new-dependencies` job
  needs PyPI packages older than 90 days; both are old enough to check). NVIDIA stays on
  `ChatOpenAI` with a base URL.
- Not verified: how `response_format=AgentAnswer` is realised per provider (a summary
  says `create_agent` picks native structured output when the model profile supports
  it); the exact `usage_metadata` keys for cache reads and writes per provider (a
  summary says the key sets differ). Both affect token budgets and the eval harness,
  and need a spike per provider before the ADR.
- The `max_retries` default in LangChain is 6 with backoff; neuron sets 0 and owns its
  retries. A new provider class must be given the same setting.
- Cost: still no dated, verifiable price source. The 0.5.0 judgement stands: do not
  ship estimated cost from guessed prices. A committed price file with a retrieval date
  and a test that fails when it is older than N days is the least-bad design.
- Operational lesson from this milestone: the nightly eval failed for six days because
  the NVIDIA account lost access to one model (404, surfaced as `configuration_error`).
  A fallback chain would have hidden that, so fallback must emit a metric and a log
  event per use, and the eval harness must pin one model and never fall back.

### Tools and MCP

Sources: https://modelcontextprotocol.io/specification/2025-11-25/server/tools,
.../basic/security_best_practices (read), the MCP schema page (annotations, read
through a summary).

- MCP tool annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`,
  `openWorldHint`) are hints. The tools page says clients **MUST** treat them as
  untrusted unless they come from trusted servers. They cannot replace neuron's
  allow-list and scopes.
- The tools page says there **SHOULD** be a human able to deny tool invocations, with
  confirmation prompts for sensitive operations. It defines no confirmation protocol.
  Servers may send `notifications/tools/list_changed`, so a tool list can change after
  review.
- The spec and its security page give no guidance on tool-description poisoning or
  rug pulls. Third-party sources (CSA, MCPTox) describe them: the description is itself
  untrusted input, and there is no pinning or signed manifest in the protocol. Mitigation
  in neuron's terms: pin tool names, descriptions and schemas in code (a hash in
  settings or a lockfile), refuse a changed definition, and never auto-allow an MCP tool
  by annotation.
- `langchain-mcp-adapters` was not researched (no primary source read); it would be a
  new dependency with a network client inside the trust boundary. A stdio server is
  local code execution (the security page requires explicit consent before running a
  configured command). Recommendation for the ADR: out of scope for v0.7.0 unless a
  concrete server is named; the registry below does not need it.
- Without MCP, "extensible" can mean a small in-repo tool registry: each tool declares
  its name, input schema, required scope, risk class (read-only, mutating) and timeout;
  the allow-list, `HIGH_RISK_TOOL_NAMES`, scope checks, span names and tests derive from
  that one declaration instead of the four places that list tools today
  (`agents/factory.py`, `security/input_policy.py`, `security/authorization.py`,
  `models/factory.py`).
- `validate_safe_url` (#167) exists; there is no fetch tool yet. Any network tool must
  also handle DNS rebinding and redirects, which `validate_safe_url` does not (it does
  no DNS resolution), and `OPERATIONS.md` already records that the service can reach
  the internet and that the helper is the only control on tool fetches.

### Memory

Sources: https://docs.langchain.com/oss/python/langchain/long-term-memory,
https://docs.langchain.com/oss/python/langgraph/stores (read);
https://langchain-ai.github.io/langmem/ (read); the Postgres store reference page
returned only a redirect and was **not** read.

- Store API: `put`/`get`/`delete`/`search`/`list_namespaces` and async twins;
  namespace is a tuple, key a string. Search without a query lists a namespace prefix
  and silently truncates at `limit`. Semantic search needs an `index` config
  (`embed`, `dims`, `fields`); changing the embedding model or dimensions needs
  re-embedding all data and there is no migration tooling.
- Inside tools the store is reached as `runtime.store` (`ToolRuntime`), and
  `create_agent` takes `store=` and `context_schema=`. Access from middleware is not
  documented. The docs recommend the namespace `(user_id, "memories")` with `user_id`
  from the runtime context, set by the application and not by the model. That matches
  neuron's rule that identity enters only through the verified principal; the namespace
  key would be the owner key (the HMAC), never the raw subject.
- The docs offer no security or privacy guidance for the store beyond "the store is
  shared within a deployment". Everything below is neuron's to design:
  per-owner namespaces, extending `GET /v1/me/export` and `DELETE /v1/me/threads` (user
  data rights, v0.4.0) to memories, retention, an off switch, size and count caps, and
  a per-owner `memories:read`/`memories:write` scope.
- OWASP ASI06 "Memory & Context Poisoning" names the main risk: a stored memory is
  untrusted input that outlives the session, so one injected instruction persists across
  threads. Mitigations to design: memories are data, rendered into the prompt in a
  delimited block and never as instructions; only user-visible, user-deletable
  memories; no memory written from tool output or retrieved content; the output guard
  and eval security suite extended with cross-session injection cases.
- Writes can be tool-driven (the model chooses) or background (an extractor runs after
  a turn). Background extraction is a second model call per turn: token cost, latency
  and a new failure mode, and it needs its own budget and timeout. Tool-driven writes
  are visible in the trajectory and can be gated by approval.
- LangMem (`langmem`: `create_manage_memory_tool`, `create_search_memory_tool`,
  `create_memory_store_manager`): the docs show no version, date or maintenance status;
  its examples use `create_react_agent` and older model names. Not verified as
  maintained, so the ADR should prefer the plain `BaseStore` API over a dependency.
- Postgres: `PostgresStore`/`AsyncPostgresStore` ship with `langgraph-checkpoint-postgres`
  (already locked, 3.2.0) and need `store.setup()`. Whether `pgvector` is required for
  semantic search, and TTL support, were **not** confirmed from a primary page (a
  LangChain forum answer says pgvector; treat as unverified). neuron's migrations
  (#143) and role split (#144) would have to cover the store's tables: `setup` runs as the
  migrator, the app role gets DML only. That is a real design task, not a flag.
- Agent Server (`langgraph.json`) supplies its own store; the `langgraph.json` graph
  is compiled without a checkpointer for the same reason (ADR 0005), so memory needs the
  same two-path handling.

### Security framing

- OWASP Top 10 for Agentic Applications 2026 (Dec 2025, CC BY-SA 4.0,
  https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026; the
  item names below are from the PDF's table of contents, the descriptions were not
  read): ASI01 Agent Goal Hijack, ASI02 Tool Misuse and Exploitation, ASI03 Identity and
  Privilege Abuse, ASI04 Agentic Supply Chain Vulnerabilities, ASI05 Unexpected Code
  Execution (RCE), ASI06 Memory & Context Poisoning, ASI07 Insecure Inter-Agent
  Communication, ASI08 Cascading Failures, ASI09 Human-Agent Trust Exploitation, ASI10
  Rogue Agents.
- Mapping to v0.7.0: tools and the registry (ASI02, ASI03), MCP or any third-party tool
  source (ASI04), memory (ASI06), approvals (ASI09: an approval prompt must show the
  exact arguments, and the human is not a trust boundary if they approve by habit),
  fallback chains and background extraction (ASI08). ASI05, ASI07 and ASI10 are not
  touched while there is one agent and no code-execution tool (ADR 0001, 0003).
- Eval and security gates: the security suite (dataset v4) has no cross-session cases
  and no approval cases. Each new capability needs its cases in the same PR, and the
  nightly gate is unusable until it runs again (see the nightly-eval notes in
  CHANGELOG, Unreleased).

### Observability

- OpenTelemetry GenAI semantic conventions are still marked Development per the
  sources found (a June 2026 article claiming "stable" conflicts with two later ones),
  and no source covered memory operations or a tool-execution status. neuron already
  keeps names in `observability/semconv.py`, so new spans (`approval`, `memory.search`,
  `memory.write`) and the `interrupted` outcome belong there, tagged as neuron-specific.
  Prompts, answers, tool arguments and memory contents stay out of telemetry (the v0.5.0
  leak scan); memory counts, namespaces' hashes and sizes are fine.

### Open questions for the owner

1. What is the concrete product requirement for memory and for approvals? Without a
   tool that needs approval, HITL cannot be shown to work end to end; without a use for
   memory, ADR 0002's "no requirement" still stands.
2. Is an HITL release acceptable if it changes the agent to `checkpointer=None` and
   therefore stores the agent's internal steps in the thread (ADR 0005 supersession)?
3. Which second provider, if any (Anthropic or Google), and is a key available to run
   the live suites on it? NVIDIA stays the free development model.
4. Is the `langchain` bump to >= 1.4.6 wanted (per-call interrupts, `v3` streaming)? It
   is a framework upgrade under AGENTS.md: re-check docs, update the lock, add
   regression tests for graph state and structured output.
5. Is MCP in or out of v0.7.0? Recommendation: out, with the in-repo registry in.
6. Memory write path: tool-driven, background, or both; and the retention default.

### Proposed split (for discussion)

Four independent ADRs, in this order, each with its own issues and eval cases:
(1) provider-neutral models and fallback, plus the structured-output retry fix and a
price file; (2) a tool registry (one declaration per tool); (3) approvals, which needs
(2) for a mutating tool and a decision on `checkpointer`; (4) memory, which needs (3)
for gated writes if writes are tool-driven. Items (1) and (2) have no open product
question and could start first.
