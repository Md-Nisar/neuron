# Enterprise Scalability and Deployment Strategy

| | |
| --- | --- |
| Date | 2026-11-10 |
| Package | Document 8 of 14 |
| Evidence | Current behaviour is from `NEURON_CURRENT_ARCHITECTURE_ASSESSMENT.md`. **No capacity figure in this document is measured.** The only measurement in the repository is 8 simulated users at 0.8 requests per second for 60 seconds on one host with a fake model. Everything else is design reasoning [I]. |

## 1. Principle

Add infrastructure when a measurement shows the current design has reached a limit. The first hosted deployment under realistic load (roadmap item F0.2) produces the baseline that every stage below depends on.

## 2. Where the load actually is

An agent platform's load differs from a web application's:

| Property | Consequence |
| --- | --- |
| A run lasts seconds to minutes and is mostly waiting on a model or an application | Concurrency is bounded by open runs and connections, not CPU |
| Each run makes several model calls and several application calls | Outbound rate limits (model provider, each application) are the first ceilings reached |
| Runs are bursty per user and idle most of the time | Queueing with fair scheduling matters more than raw throughput |
| Database writes per turn are many and small (about ten transactions per turn today, from reading) | The connection pool is the first internal limit; the default maximum is 10 |

## 3. Growth stages

Thresholds are stated as symptoms to watch for, not user counts, because no counts are measured.

### Stage 1: one organisation, about 5 applications

| Aspect | Design |
| --- | --- |
| Topology | Current one: API replicas, one worker, one Postgres, blob store. Add a second worker role for runs when durable runs land. |
| Tenancy | Single-organisation deployment. The organisation id exists in the data model from the start. |
| Queue | Postgres job tables (Procrastinate is already a dependency). |
| Scaling | Two API replicas for availability. One or two run workers. |
| Change needed | Separate connection pools for admission control (rate limits, leases, budgets) and for work (checkpoints, knowledge, run events), so slow queries cannot starve admission (assessment 7.10). |

### Stage 2: one organisation, about 20 applications, several departments, hundreds of concurrent runs

Move to this stage when: pool saturation or queue wait appears in metrics, or one application's slowness affects others.

| Aspect | Design |
| --- | --- |
| Workers | Separate pools by job type: interactive runs, background and event-triggered runs, ingestion, housekeeping. Interactive runs get reserved capacity. |
| Bulkheads | Per-application concurrency limits and circuit breakers in the executor. Per-department and per-agent run quotas. |
| Connections | A connection pooler (PgBouncer) in front of Postgres. HTTP connection reuse per application (today MCP opens a connection per call). |
| Database | Partition run events and audit records by time. Read replica for listing, audit queries and exports. Checkpoint pruning within threads. |
| Caching | Short-lived caches for manifests, policies and packs with explicit invalidation on publish. JWKS caching exists. No caching of application data. |
| Events | Webhook ingress writes to the job table and returns immediately. |

### Stage 3: about 100 applications, thousands of users, multiple regions, or several organisations

Move to this stage only with a customer who needs it.

| Aspect | Design |
| --- | --- |
| Multi-tenancy | Organisation id plus row-level security for shared deployments; a dedicated database per organisation for those that require it. The application code is the same. |
| Regions | A cell per region: full stack and data stay in region. A thin global directory maps organisations to cells. No cross-region database. |
| Queue | Re-evaluate Postgres job tables against a dedicated durable-execution engine or broker, using measured queue latency. |
| Catalogue scale | With thousands of capabilities, catalogue search needs an index (full-text plus embeddings, both already available through pgvector). |
| Connector workers | A separate executor pool, possibly placed in a customer network segment that can reach private applications (section 7). |

## 4. Topic by topic

| Topic | Position |
| --- | --- |
| **Multi-tenancy** | Data model from day one; shared-deployment isolation only in stage 3. |
| **Tenant isolation** | Organisation id on every row, enforced in SQL and by row-level security, as the Knowledge Engine does per owner today. Per-organisation credentials, policies, quotas and encryption keys. Isolation tests in the security suite. |
| **Horizontal scaling** | API replicas are already close to stateless once per-process stream slots and counters move to the database or disappear with durable runs. Workers scale by adding processes. |
| **Background execution** | Durable runs on the job queue. Needed for approvals, events and long tasks. |
| **Queue architecture** | Postgres job tables first: one fewer system to operate, transactional enqueue with business data. Known limits: throughput in the low thousands of jobs per second at best and vacuum pressure [K]. Neuron is far below that. |
| **Event processing** | At-least-once delivery from the application; deduplication by event id; each event becomes at most one run through an idempotency key. |
| **Distributed execution** | Workers claim jobs with a lease and heartbeat. Fencing tokens on writes so a stale worker cannot commit (assessment 7.4 notes leases have neither today). |
| **Connection pooling** | Split pools now; PgBouncer in stage 2. |
| **Rate limiting** | Three layers: inbound per user and organisation (exists per user), outbound per application, outbound per model provider. |
| **Caching** | Configuration only. Provider-side prompt caching is helped by a stable prompt prefix. |
| **Database scaling** | Vertical first; partitioning and a replica in stage 2; per-organisation databases or cells in stage 3. Sharding is not planned. |
| **High availability** | Two API replicas and two workers across zones; managed Postgres with automatic failover; runs resume after failover because they are durable. |
| **Disaster recovery** | Point-in-time recovery for Postgres; versioned blob storage; secrets backend backup; a restore exercise in the hosted environment with measured recovery time and data loss. Targets are set after the first exercise. |
| **Backup and restoration** | The credential store and the audit ledger are backed up with the database but restored with care: restored refresh tokens may already be rotated, so users may need to reconnect. |
| **Observability** | Existing OpenTelemetry traces and metrics, plus: queue depth and wait, per-application latency and error rate, policy decision counts, approval latency, per-organisation and per-agent cost. |
| **Cost allocation** | The token ledger gains organisation, department, agent and application dimensions. Model cost by provider price table; application call counts for applications that charge per call. |
| **Resource quotas** | Tokens, concurrent runs, runs per day, storage, per organisation, department and agent. |

## 5. Separate workers: recommendation

| Worker | When to introduce | Why |
| --- | --- | --- |
| Ingestion worker | Exists | Different database role and workload |
| Run worker | With durable runs | Runs must survive API restarts |
| Separate interactive and background run pools | Stage 2 | Protect interactive latency |
| Connector (executor) worker | Stage 3, or earlier if a customer needs private-network placement | Network placement and blast-radius isolation for credentials |
| Workflow worker | Not separate | Workflows are runs with more steps |

Not recommended: a message broker, a separate vector database, a graph database, a service mesh, or Kubernetes operators, until a measured need appears.

## 6. Deployment models

| Model | Meaning | Demand signal | Recommendation |
| --- | --- | --- | --- |
| **Self-hosted on a single host** | Docker Compose reference stack | Evaluation, small teams | **Essential.** Exists; keep working. |
| **Customer-managed cloud** | The customer runs the containers on their own cloud account with managed Postgres | The primary target user | **Essential.** Provide a Helm chart or equivalent, a sizing guide and an upgrade path. |
| **On-premises, possibly air-gapped** | No internet; self-hosted model; offline image registry | Regulated and public sector | **Essential in design, deliverable in the second half of the plan.** Requires no hard dependency on any hosted service, which is already true except the model. |
| **Private cloud managed by the project's company** | A dedicated instance per customer, operated for them | Customers who want the isolation without the operations | Defer until a paying customer asks. Mostly an operations capability. |
| **Multi-tenant SaaS** | One shared service | Easiest adoption for small teams | **Defer beyond 18 months.** It needs stage 3 isolation, an on-call organisation and compliance attestations. |
| **Hybrid: hosted control plane, customer-side executors** | The pattern MuleSoft, Boomi and Kong use [K] | Reaching private applications from a hosted service | Only relevant if SaaS happens. |

Why self-hosted first: it is the differentiator (document 4), it needs no compliance attestation from the project, and it defers the hardest scaling work.

## 7. Reaching applications on private networks

Enterprise applications often sit behind firewalls. In the self-hosted models Neuron runs inside the same network, so the question reduces to egress policy:

- The egress backend currently allows public addresses only. Private applications need a per-application allow-list entry naming the exact host, never a general switch.
- Outbound proxies and custom certificate authorities must be configurable per application.

## 8. Operational requirements for the first hosted deployment

| Item | Why |
| --- | --- |
| Resolve the `sslmode=verify-full` blocker noted in `render.yaml` | The deployment is marked not deployable until it is |
| Load baseline with a real model | Replaces the fake-model figure |
| Restore and rollback exercised and timed | Sets recovery objectives from evidence |
| Dashboards for the metrics in section 4 | Shows which stage 2 trigger arrives first |
| A written upgrade procedure including migrations | Self-hosting customers upgrade on their own |

## 9. Cost model sketch

No prices are assumed. The structure:

| Cost | Driver | Lever |
| --- | --- | --- |
| Model tokens | Steps per run, context size | Capability selection, context management, cheaper models for sub-tasks, prompt caching |
| Compute | Concurrent runs (memory per worker), not request rate | Async workers, release workers during approvals |
| Database | Run events, checkpoints, audit growth | Retention, partitioning, pruning |
| Embeddings and parsing | Documents ingested | Existing quotas |
| Application API usage | Calls per run for metered applications | Per-application budgets |
| Operations | Number of moving parts | The reason to stay on Postgres |

Cost per completed workflow is a headline metric in `NEURON_SUCCESS_METRICS.md`.
