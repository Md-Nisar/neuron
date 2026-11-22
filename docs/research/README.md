# Research

Background studies and decision proposals. Nothing here is built or decided until an ADR in `docs/decisions/` or a backlog story says so. Product facts come from `enterprise-strategy/architecture/NEURON_CURRENT_ARCHITECTURE_ASSESSMENT.md`.

| Folder | What it holds |
|---|---|
| `rag/` | The three consolidated RAG reports. Inputs to ADR 0014 and `docs/product/NEURON_RAG_PRODUCT_BACKLOG.md`. |
| `data-analytics/` | Everything on structured data and NL-to-SQL. Start at its `README.md`: reading order, what each document proposes, what is built, and where the documents differ. |
| `agent-ui/` | A2UI assessment and handoff. |
| `enterprise-strategy/vision-and-roadmap/` | Vision, 18-month and must-have roadmaps, success metrics, Opus handoff. |
| `enterprise-strategy/use-cases/` | Problem analysis, first three use cases, first use case and build-vs-buy, evidence-backed use cases. |
| `enterprise-strategy/architecture/` | Current architecture assessment, global agent architecture, domain-agnostic integration, security, scalability, build vs integrate, the 2026-11 enterprise agent audit (scorecard and roadmap). |
| `enterprise-strategy/market/` | Market research, competitive positioning, feature catalog, domain adaptation. |

Notes:
- Some documents overlap (the three use-case studies, the two roadmaps). Read the one closest to your question and check its date.
- `data-analytics/NAO_LICENSE_AND_FIT_ASSESSMENT.md` opens with the title "Data Analytics Agents: Landscape and Prior Art for Neuron".
- Earlier release research stays beside its release: `docs/research-notes.md`, `docs/releases/v0.9.0-research.md`, `docs/ai-code-verification/research.md`.
- Documents do not yet carry a status (draft, accepted, superseded). Add one when a document is acted on.
