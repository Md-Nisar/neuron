| Release    | Theme                      | Primary outcome                       |
| ---------- | -------------------------- | ------------------------------------- |
| **v0.1.0** | Functional Agent Runtime   | ✅ Real agent works                    |
| **v0.2.0** | Reliable Agent Runtime     | ✅ Predictable failures + resilience   |
| **v0.3.0** | Stateful + Streaming       | ✅ Conversations + real-time responses |
| **v0.4.0** | Secure Multi-User          | ✅ Authentication + authorization      |
| **v0.5.0** | Evaluation + Observability | ✅ Measure quality + production behavior |
| **v0.6.0** | Production Deployment      | 🟡 Prepared (0.6.0 on `main`, not tagged) |
| **v0.7.0** | Extensible Agent Platform  | 🟡 Implemented, release gate pending (tracker #253) |
| **v0.8.0** | User Application           | Web UX + chat experience              |
| **v0.9.0** | Production Candidate       | Load/security/DR/release freeze       |
| **v1.0.0** | Production AI Application  | Stable production platform            |

v0.5.0 is designed in [ADR 0007](decisions/0007-evaluation-and-observability.md) and tracked by the issues labelled `v0.5.0`.

v0.6.0 is designed in [ADR 0008](decisions/0008-production-deployment.md) and tracked by the issues labelled `v0.6.0`.

v0.7.0 is designed in [ADR 0009](decisions/0009-extensible-agent-platform.md) and tracked by the issues labelled `v0.7.0` (tracker #253).

v0.8.0 is designed in [ADR 0010](decisions/0010-user-application.md) (Accepted; issue drafts in `docs/releases/v0.8.0-issues.md`). Thread title and feedback storage: [ADR 0011](decisions/0011-thread-metadata-storage.md). The code is merged and the version is 0.8.0, but the release gate is open: nothing ran against a real Keycloak or browser ([record](releases/v0.8.0-release-verification.md)). Nothing is tagged.

v0.9.0 is proposed in [ADR 0012](decisions/0012-production-candidate.md) (research: `docs/releases/v0.9.0-research.md`; issue drafts: `docs/releases/v0.9.0-issues.md`). Everything is measured on a local reference stack; hosted deployment stays after v1.0.0.
