| Release    | Theme                      | Primary outcome                       |
| ---------- | -------------------------- | ------------------------------------- |
| **v0.1.0** | Functional Agent Runtime   | ✅ Real agent works                    |
| **v0.2.0** | Reliable Agent Runtime     | ✅ Predictable failures + resilience   |
| **v0.3.0** | Stateful + Streaming       | ✅ Conversations + real-time responses |
| **v0.4.0** | Secure Multi-User          | ✅ Authentication + authorization      |
| **v0.5.0** | Evaluation + Observability | ✅ Measure quality + production behavior |
| **v0.6.0** | Production Deployment      | ✅ Released (gate #160 closed 2026-10-29 without a Render deployment or OpenAI run) |
| **v0.7.0** | Extensible Agent Platform  | ✅ Released (tracker #253 closed 2026-10-29 without an OpenAI run) |
| **v0.8.0** | User Application           | ✅ Released (gate #293 closed 2026-10-29; the owner reports the real browser and Keycloak run is done) |
| **v0.9.0** | Production Candidate       | ✅ Released (local reference stack only) |
| **v1.0.0** | Production AI Application  | ✅ Released 2026-11-02 without a production environment ([record](releases/v1.0.0-release-verification.md)) |
| **v1.1.0** | Personal Knowledge         | ✅ Released 2026-11-10 as "Knowledge Engine" without a production environment: private knowledge bases, document upload, cited answers ([record](releases/v1.1.0-release-verification.md), [ADR 0014](decisions/0014-knowledge-engine.md)) |

v0.5.0 is designed in [ADR 0007](decisions/0007-evaluation-and-observability.md) and tracked by the issues labelled `v0.5.0`.

v0.6.0 is designed in [ADR 0008](decisions/0008-production-deployment.md) and tracked by the issues labelled `v0.6.0`.

v0.7.0 is designed in [ADR 0009](decisions/0009-extensible-agent-platform.md) and tracked by the issues labelled `v0.7.0` (tracker #253).

v0.8.0 is designed in [ADR 0010](decisions/0010-user-application.md) (Accepted; issue drafts in `docs/releases/v0.8.0-issues.md`). Thread title and feedback storage: [ADR 0011](decisions/0011-thread-metadata-storage.md). The code is merged and the version is 0.8.0, but the release gate is open: nothing ran against a real Keycloak or browser ([record](releases/v0.8.0-release-verification.md)). Tagged as v0.8.0 on 2026-10-28 with the gate deferred.

v0.9.0 is designed in [ADR 0012](decisions/0012-production-candidate.md) (research: `docs/releases/v0.9.0-research.md`; issue drafts: `docs/releases/v0.9.0-issues.md`), Accepted 2026-10-28, and tracked by the issues labelled `v0.9.0` (tracker #338). Everything is measured on a local reference stack; hosted deployment stays after v1.0.0.

v1.0.0 is the v0.9.0 candidate plus fixes, tests and the login theme, with no contract change. The owner released it directly, without the `v1.0.0-rc.N` candidates of ADR 0012 decision 12, because no production environment exists; the load re-run against the v0.9.0 baseline is still to be done ([record](releases/v1.0.0-release-verification.md)).

v1.1.0 ("Personal Knowledge") is designed in [ADR 0014](decisions/0014-knowledge-engine.md), Accepted 2026-11-02. Released 2026-11-10 (tag `v1.1.0`). Scope: RAG-E00 to RAG-E08 in the [RAG backlog](product/NEURON_RAG_PRODUCT_BACKLOG.md); status in the [tracker](product/RAG_IMPLEMENTATION_TRACKER.md). v1.2.0 (RAG-E09, sharing and retrieval quality) is a proposal.

## Deferred until after v1.0.0

| Item | What is left | Owner release |
| --- | --- | --- |
| Hosted Render deployment, pipeline, restore and rollback on Render, OpenAI production model, Anthropic live, staging and production runs | Never run; #160 and #253 were closed on 2026-10-29 without them | after v1.0.0 |
| #285 | Forwarding ratings to LangSmith | after v1.0.0 (design check and proposed ADR 0013: the run ID already is the LangSmith run ID) |
| External penetration test | ADR 0012 open question 2 | after v1.0.0 |
