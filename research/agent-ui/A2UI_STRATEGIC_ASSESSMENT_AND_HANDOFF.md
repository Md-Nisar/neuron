# Neuron × A2UI — Strategic Assessment, Architecture Decision & Implementation Handoff

Nov 12, 2026

## 1. Executive recommendation

**Decision: CONDITIONAL GO, confidence 70%.** Adopt A2UI v1.0 as the wire format for generated UI, behind a Neuron-owned presentation boundary. Do not adopt the A2UI agent SDK, AG-UI transport or the stock Basic catalog as-is.

The case for it: A2UI is declarative data, not code, which matches Neuron's rule that model output is untrusted. Its v1.0 specification is marked stable and transport-agnostic, so it fits inside Neuron's existing SSE contract without a second protocol.

The case against rushing: Neuron has eight built-in tools and no data source that needs a dashboard today. The A2UI packages are at 0.x and ship breaking changes about every two weeks. The React renderer's default Markdown path uses raw HTML injection, which Neuron's lint and CSP forbid. Each of these is a gate below, not a blocker.

| Question | Answer |
| --- | --- |
| 1. Should Neuron integrate A2UI? | Yes, conditionally. Integrate after gates G1 to G3 pass in a spike that writes no production code. |
| 2. Ideal strategy? | Hybrid. A2UI v1.0 messages as payload, carried in Neuron's own `final` event and thread history, validated server-side against a Neuron-curated catalog. |
| 3. What does it unlock? | Structured results (cited sources, document status, comparisons), forms for clarification, and later tool-driven dashboards, on any A2UI renderer. |
| 4. What must Opus follow? | Eight ADR decisions in section 6. The three that matter most: server validates every surface; approvals never render through A2UI; `AgentAnswer` stays flat. |
| 5. What comes first? | Phase 0 spike, then Phase 1: read-only, server-composed surfaces for knowledge results, delivered in `final` and history. No model-generated UI yet. |
| 6. What enters the roadmap? | Interactive actions (Phase 2), model-composed surfaces with evals (Phase 3), MCP-delivered UI and progressive streaming (Phase 4). |

**How to read this document.** Statements tagged **Verified** were read in source at Neuron `0f78ef9` and A2UI `8bf644a`, both dated 2026-11-12. **Assumption** marks what was not tested. **Proposed** marks new modules that do not exist yet. Nothing was run, built or modified.

## 2. Verified Neuron architecture assessment

Neuron is a secure single-agent chat service with private RAG, not yet an agent platform. Its security engineering is well ahead of its agent capability, and its UI is text-only by deliberate design.

### What is implemented

| Area | Verified state | Evidence |
| --- | --- | --- |
| Runtime | One-node LangGraph (`START -> agent -> END`) wrapping one LangChain `create_agent` loop with up to 11 middlewares. No planner, no sub-agents. | [`graphs/main_graph.py`](https://github.com/Md-Nisar/neuron/blob/main/src/neuron_agent/graphs/main_graph.py), [`models/factory.py`](https://github.com/Md-Nisar/neuron/blob/main/src/neuron_agent/models/factory.py) |
| Output contract | `AgentAnswer`: flat structured output (`answer`, `used_tools`, `confidence`, `refused`, `clarification_needed`, `citations`, `not_in_documents`). | [`schemas/agent.py`](https://github.com/Md-Nisar/neuron/blob/main/src/neuron_agent/schemas/agent.py) |
| Streaming | SSE, protocol version 1, seven events: `run_started`, `token`, `tool_call`, `final`, `approval_required`, `error`, `done`. Deltas are a preview; `final` is authoritative. Not resumable. | [`services/streaming.py`](https://github.com/Md-Nisar/neuron/blob/main/src/neuron_agent/services/streaming.py), [`services/agent_service.py`](https://github.com/Md-Nisar/neuron/blob/main/src/neuron_agent/services/agent_service.py) |
| Tools | `utc_now`, `calculator`; memory `recall`, `remember`, `forget`; three knowledge tools (list, search, excerpt). One `ToolSpec` per tool: scope, risk, source, taint. | [`tools/registry.py`](https://github.com/Md-Nisar/neuron/blob/main/src/neuron_agent/tools/registry.py), [`knowledge/tools.py`](https://github.com/Md-Nisar/neuron/blob/main/src/neuron_agent/knowledge/tools.py) |
| MCP | Operator-configured Streamable HTTP servers, hash-pinned tool definitions, read once at start-up. Replies are **text only**; any other content block is an error. No sampling, roots or elicitation. | [`tools/mcp/client.py`](https://github.com/Md-Nisar/neuron/blob/main/src/neuron_agent/tools/mcp/client.py) |
| Approvals | `HumanInTheLoopMiddleware` interrupts before `mutating` tools and before MCP calls on a tainted run. Resumed by `POST /v1/threads/{id}/approvals/{approval_id}` and its `/stream` variant. | [`api/main.py`](https://github.com/Md-Nisar/neuron/blob/main/src/neuron_agent/api/main.py) |
| RAG | Hybrid dense plus full-text retrieval with RRF, RLS in Postgres, server-minted and server-validated citations stamped on the stored answer. | [`knowledge/retrieval.py`](https://github.com/Md-Nisar/neuron/blob/main/src/neuron_agent/knowledge/retrieval.py), [`knowledge/citations.py`](https://github.com/Md-Nisar/neuron/blob/main/src/neuron_agent/knowledge/citations.py) |
| Persistence | LangGraph checkpoints in Postgres. Only the user turn and final answer are stored; tool calls and results are discarded after each run. | [`ARCHITECTURE.md`](https://github.com/Md-Nisar/neuron/blob/main/ARCHITECTURE.md) |
| Security | JWT with JWKS, HMAC owner key, per-run `AuthorizationContext` outside graph state, taint tracking, output leak guard, fail-closed budgets and leases. | [`security/`](https://github.com/Md-Nisar/neuron/tree/main/src/neuron_agent/security) |
| Frontend | React 19, Vite, strict TypeScript SPA on its own origin. Hand-written SSE reader with runtime payload checks. Markdown rendered as React elements only; images never loaded. | [`web/src/lib/stream/events.ts`](https://github.com/Md-Nisar/neuron/blob/main/web/src/lib/stream/events.ts), [`web/src/features/chat/Markdown.tsx`](https://github.com/Md-Nisar/neuron/blob/main/web/src/features/chat/Markdown.tsx) |
| Browser policy | CSP `default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'`, no inline anything, `form-action 'none'`, `worker-src 'none'`. | [`scripts/web_headers.py`](https://github.com/Md-Nisar/neuron/blob/main/scripts/web_headers.py) |

### What is not implemented

- **Any structured or generative UI.** The only non-text UI the server drives is the approval card and the citation list.
- **Production deployment.** Every release through v1.1.0 was verified on a local Docker Compose stack only ([`docs/ROADMAP.md`](https://github.com/Md-Nisar/neuron/blob/main/docs/ROADMAP.md)).
- **Durable or background runs, per-request model choice, dynamic tools, planning.** Named as gaps in Neuron's own [current architecture assessment](https://github.com/Md-Nisar/neuron/blob/main/research/enterprise-strategy/architecture/NEURON_CURRENT_ARCHITECTURE_ASSESSMENT.md).
- **Knowledge sharing (v1.2.0, RAG-E09).** A proposal only.

### Five facts that constrain an A2UI integration

1. **`AgentAnswer` must stay flat.** `AnswerTokenExtractor` finds the answer by matching `"answer": "` in partial JSON. A nested object in the response format can break token streaming.
2. **Tool arguments and results are never streamed.** `tool_call` events carry the name only ([`SECURITY.md`](https://github.com/Md-Nisar/neuron/blob/main/SECURITY.md)). A UI payload cannot ride on the existing `tool_call` event.
3. **Protocol adapters were rejected once.** ADR 0010 decision 4 chose a hand-written stream client over AG-UI, AI SDK and LangGraph SDK because the approval path is security-critical ([ADR 0010](https://github.com/Md-Nisar/neuron/blob/main/docs/decisions/0010-user-application.md)).
4. **The client and server contract is pinned by a test.** `tests/unit/test_web_stream_contract.py` compares `web/src/lib/stream/contract.json` to the server models and the exact event list. Unknown events are ignored by the client; unknown fields in `final` are additive (precedent: citations, RAG-05.02).
5. **New dependencies must be at least 90 days old.** `scripts/check_new_dependencies.py` and `scripts/check_new_npm_dependencies.py` enforce `MIN_AGE_DAYS = 90`; web packages are pinned to exact versions.

A sixth point is a product fact, not a code fact: the Agent Server path (`langgraph.json`) runs the same graph without budgets, leases, memory or knowledge. Generated UI should not be offered there.

## 3. A2UI capabilities and opportunities

A2UI is a declarative protocol in which an agent describes UI as JSON and the client renders it with its own components. Its specification is stable at v1.0; its libraries are not.

### Protocol (v1.0, current)

| Aspect | What the spec defines | Source |
| --- | --- | --- |
| Agent to renderer | Six envelope messages: `createSurface`, `updateComponents`, `updateDataModel`, `deleteSurface`, `callRendererFunction`, `agentFunctionResponse`. | [Protocol spec v1.0](https://a2ui.org/specification/v1.0-a2ui/) |
| Renderer to agent | Four messages: `action`, `callAgentFunction`, `rendererFunctionResponse`, `error`. | Same |
| Composition | A flat list of components linked by ID (adjacency list). One component has `id: "root"`. Structure and data are separate; components bind to a JSON data model by path. | Same |
| Catalog | The client declares which components and functions exist. An agent can only reference catalog entries. Custom catalogs are first-class. | [`catalog_definition.json`](https://github.com/a2ui-project/a2ui/blob/main/specification/v1_0/json/catalog_definition.json) |
| Basic catalog | 18 components (Text, Image, Icon, Video, AudioPlayer, Row, Column, List, Card, Tabs, Divider, Modal, Button, CheckBox, TextField, DateTimeInput, ChoicePicker, Slider) and 15 functions including `openUrl`. | Same spec, Basic Component Catalog |
| Transport | Agnostic. Requires ordered delivery, message framing and a metadata channel. Bindings are documented for AG-UI, A2A and MCP; SSE, WebSockets and REST are listed as valid. | Same spec, Transport decoupling |
| Validation | A prompt, generate, validate loop with a standard error shape (`VALIDATION_FAILED`, a JSON pointer, a message) for model self-correction. | Same spec |
| Stability | v1.0 is `current`; v0.9.1 and v0.9 are `previous`; v0.8 is `deprecated`. The v1.0 README says breaking changes go to a future major version. | [`versions.json`](https://github.com/a2ui-project/a2ui/blob/main/specification/versions.json), [v1.0 README](https://github.com/a2ui-project/a2ui/blob/main/specification/v1_0/README.md) |

### Libraries (as published on 2026-11-12)

| Package | Version | Finding |
| --- | --- | --- |
| [`@a2ui/react`](https://www.npmjs.com/package/@a2ui/react) | 0.15.0 | Supports React 18 and 19. Since 0.13 the Basic catalog renders as Lit custom elements, not React components. Custom catalogs can be pure React. |
| [`@a2ui/web_core`](https://www.npmjs.com/package/@a2ui/web_core) | 0.15.0 | Required by the React renderer. Depends on `lit`, `zod`, `@preact/signals-core`. About 8.5 MB unpacked. |
| [`@a2ui/markdown-it`](https://www.npmjs.com/package/@a2ui/markdown-it) | 0.2.2 | Optional Markdown renderer: markdown-it plus DOMPurify, returns HTML. |
| [`a2ui-core`](https://pypi.org/project/a2ui-core/) (Python) | 0.6.0 | Protocol models, data binding, catalog validation. Needs `pydantic`, `jsonschema`, `referencing`, `regex`, `babel`. Four releases between 2026-10-08 and 2026-11-10. |
| [`a2ui-agent-sdk`](https://pypi.org/project/a2ui-agent-sdk/) (Python) | 0.11.0 | Prompt generation, catalog negotiation, an "Express" inference format compiled to A2UI. Adds an ANTLR runtime. First-party adapters exist for ADK and A2A only. |
| [`@a2ui/catalog-mcp`](https://www.npmjs.com/package/@a2ui/catalog-mcp) | 0.0.3 | Lets a surface call MCP tools and render A2UI or MCP Apps returned by them. Very early. |

### Maturity, read critically

- **The spec is stable; the SDKs are churning.** `a2ui-core` 0.6.0 alone lists at least five breaking changes, and the React changelog has an unreleased breaking change on top of 0.15.0 ([core changelog](https://github.com/a2ui-project/a2ui/blob/main/python/a2ui_core/CHANGELOG.md), [React changelog](https://github.com/a2ui-project/a2ui/blob/main/typescript/renderers/react/CHANGELOG.md)).
- **LangGraph support goes through AG-UI.** The official any-framework guide routes LangGraph through AG-UI tooling, with CopilotKit under some scaffolds ([guide](https://github.com/a2ui-project/a2ui/blob/main/docs/public/guides/a2ui-with-any-agent-framework.md)). There is no first-party LangChain adapter.
- **Renderers exist for React, Lit, Angular, Flutter, SwiftUI and Jetpack Compose**, per the [official roadmap](https://a2ui.org/roadmap/). The same page makes no production-readiness claim and says plans can change.
- **Templates, sandboxed logic and evals are roadmap items**, not shipped features ([README roadmap](https://github.com/a2ui-project/a2ui/blob/main/README.md)).
- **No production deployments are named** in the coverage reviewed ([InfoQ, July 2026](https://infoq.com/news/2026/07/google-a2ui-genui)). The same report records concerns about UI impersonation and catalog-driven sameness.

### Security model

A2UI's safety claim is structural: UI is data validated against a schema, and every capability is granted by the app developer through the catalog. The renderer README is explicit that the rest is the integrator's job: agent messages are untrusted input, with phishing, script injection through property values and layout-complexity denial of service named as risks ([React README, Security](https://github.com/a2ui-project/a2ui/blob/main/typescript/renderers/react/README.md)).

Three specifics matter for Neuron:

1. **Verified:** the universal Basic catalog's Markdown directive injects rendered HTML through Lit's `unsafeHTML` ([`markdown.ts`](https://github.com/a2ui-project/a2ui/blob/main/typescript/core/web_core/src/universal/basic_catalog/directives/markdown.ts)). The React renderer offers `MarkdownComponentContext`, which accepts an app React component instead, so Neuron's own `Markdown.tsx` can be used.
2. **Verified:** Basic `Image`, `Video` and `AudioPlayer` load URLs, and `openUrl` opens them. Neuron treats an image URL as an exfiltration channel and never loads one.
3. **Assumption:** the Lit-based catalog styles through `adoptedStyleSheets`. Whether every path works under `style-src 'self'` was not tested. This is gate G2.

### How it can meet Neuron

Neuron's transport already satisfies the A2UI transport contract: SSE gives ordered, framed delivery, and the JSON event payload gives a metadata channel. A2UI messages can therefore travel as a field of an existing event, with no AG-UI layer. The return channel (`action`) maps onto a new authenticated route shaped like the existing approvals route.

## 4. Problems solved and capabilities unlocked

A2UI solves a presentation problem Neuron has only in a small way today, and a larger one it will have once its tool surface grows. The value is real but back-loaded.

### Problems it solves

| Problem in Neuron today | With A2UI | Honest size of the win now |
| --- | --- | --- |
| Every answer is Markdown text. Tabular or multi-item results (search hits, document lists) are prose. | Cards, lists and tabs composed from tool results. | Medium. Knowledge results are the one strong case. |
| `clarification_needed` produces a free-text question. The user types a free-text reply. | A short form with typed inputs, returned as a structured `action`. | Medium. Reduces turns for multi-field clarifications. |
| Each new rich element (citations, approval card) needs a bespoke event field, parser, reducer and component. | One generic surface pipeline; new presentations become catalog entries or templates. | High over time, low on day one. |
| MCP tools return text only, so a tool cannot present its own result. | A pinned, validated UI contract per tool. | None now. Requires an ADR 0009 amendment first. |
| The web client is the only client. | Any A2UI renderer (Flutter, SwiftUI, Compose) can show the same surfaces. | None now. No second client exists. |

### Capabilities unlocked, in order of risk

1. **Server-composed surfaces.** Neuron code builds A2UI from trusted tool artifacts. The model decides nothing about layout. Example: knowledge search results as source cards with page ranges.
2. **Interactive workflows.** Buttons and forms send `action` messages that start the next turn. Example: pick which knowledge base to search, or fill three missing fields at once.
3. **Model-composed surfaces.** The model calls a UI tool with a component tree drawn from the curated catalog. Example: a side-by-side comparison of two documents.
4. **Dashboards.** Long-lived surfaces updated by `updateDataModel`. Example: ingestion status across a knowledge base. Needs data sources Neuron does not have yet, and benefits from resumable streams, which Neuron lacks.
5. **MCP-driven experiences.** An MCP server supplies a layout as an `a2ui://` resource and per-call data ([A2UI over MCP guide](https://github.com/a2ui-project/a2ui/blob/main/docs/site/src/content/docs/guides/a2ui-over-mcp.mdx)). Example: a ticketing server that renders its own ticket view.

### Product differentiation

- **Auditable generative UI.** Most generative-UI stacks trust the model or sandbox its HTML. Neuron can offer UI that is server-validated, catalog-bound, taint-aware and recorded in history, consistent with how it already treats citations and `used_tools`.
- **A standard on the wire.** An enterprise buyer can point a non-web client at Neuron without a Neuron-specific UI schema.
- **Approvals that cannot be spoofed.** Keeping approvals outside the generated-UI channel is a selling point, not a limitation.

### The challenge to the idea

Neuron's own assessment ranks agent capability, durable runs and module size above presentation. If those are not addressed, A2UI will render very little: an agent with a calculator and a clock has nothing to put on a dashboard. This is why Phase 1 is deliberately small and tied to the one feature with structured output today, the Knowledge Engine.

## 5. Recommended integration architecture

Use the hybrid: A2UI v1.0 as the payload format, inside a small Neuron-owned presentation module, carried by Neuron's existing stream and history. It is the only option that keeps the security-critical paths unchanged.

### Strategy comparison

Scores are 1 (poor) to 5 (good), judged from the code read for this assessment.

| Criterion | A. Direct integration | B. Dedicated presentation layer | C. Hybrid (recommended) |
| --- | --- | --- | --- |
| What it is | A2UI agent SDK in the agent loop, AG-UI transport, stock renderer and Basic catalog | A separate service or second model call that converts answers into A2UI | A2UI messages as data, validated in-process, carried in `final` and history |
| Compatibility | 2. Replaces the stream contract ADR 0010 chose to keep | 4. Core untouched | 5. Additive fields only |
| Security | 2. Approval path shares a protocol adapter; Basic catalog loads media | 3. New service, new trust boundary, second prompt surface | 5. One validator, one catalog, existing authorization |
| Streaming | 4. Progressive UI out of the box | 2. UI arrives after a second hop | 3. Whole surface in `final` first; progressive later |
| Extensibility | 4. Full protocol from day one | 3. Flexible but duplicated context | 4. Grows by catalog entries, composers and one tool |
| Maintainability | 2. Tracks three 0.x packages plus AG-UI | 2. Two deployables, two release trains | 4. One schema pin, thin dependency |
| Complexity | 2. Large first change | 2. Extra infrastructure | 4. Small first change |
| Scalability | 3. Same process | 4. Scales separately | 3. Same process; payload caps bound cost |
| **Total (of 35)** | **19** | **20** | **28** |

### Components

| Component | Status | Responsibility | Boundary |
| --- | --- | --- | --- |
| `presentation/catalog` | Proposed | The Neuron catalog: the allow-list of components and functions, with a stable `catalogId`. | Only place that names what UI can exist. |
| `presentation/validation` | Proposed | Validates every surface against the A2UI v1.0 schema, the catalog and Neuron limits. | Nothing reaches a client or a checkpoint without passing it. |
| `presentation/composers` | Proposed | Deterministic builders from trusted tool artifacts to A2UI messages. | No model input decides structure. |
| `presentation/surfaces` | Proposed | Stamps validated surfaces on the stored answer and reads them back. | Mirrors `knowledge/citations.py`. |
| `presentation/actions` | Proposed, Phase 2 | Validates an inbound `action` against the stored surface and frames it as a user turn. | Never calls a tool directly. |
| UI tool (`render_ui`) | Proposed, Phase 3 | Lets the model request a surface. Its arguments are validated, never streamed raw. | One `ToolSpec`, scope `tools:render_ui`, risk `read`. |
| `AgentService` | Verified, reuse | Adds surface fields to the response exactly as it adds citations. | No new run model. |
| `web/src/lib/stream` | Verified, extend | Runtime-checks the new fields; rejects malformed payloads as protocol errors. | Same pattern as `citations.ts`. |
| `web/src/features/surfaces` | Proposed | Renders surfaces inside fixed chrome using Neuron's own components. | Never renders approvals. |

### Wire format

Surfaces travel as additive, nullable fields beside citations, on the `final` event, the `/invoke` response and each assistant `ThreadMessage`:

- `surfaces`: a list of `{surface_id, messages}`, where `messages` are unmodified A2UI v1.0 agent-to-renderer envelopes.
- `surface_schema_version`: `1`.
- `a2ui_version`: `"1.0"`.

All three are null unless the run produced a surface, the same rule citations follow. Field names are a recommendation; Opus may adjust them but must keep them flat siblings of `citations`.

### Render flow (Phase 1)

1. The run executes as today. A knowledge tool returns its content and artifact.
2. In `_final_answer`, after citations are validated, a composer builds a surface from the kept citations.
3. The validator checks it. A rejected surface is dropped, counted and logged without content; the text answer is unaffected.
4. The graph stamps the surface on the stored `AIMessage` with the `run_id`, beside the citation stamp.
5. `AgentService` copies the stamp into the response; `final` and thread history expose it.
6. The web client validates the shape, then renders it under a fixed "Generated view" header below the answer text.

### Action flow (Phase 2)

1. The user activates a control. The renderer produces an A2UI `action`: name, `surfaceId`, `sourceComponentId`, timestamp, resolved context.
2. The client posts it with the bearer token to a new thread-scoped stream route.
3. The server authorizes the caller, resolves and leases the thread, and reserves budget, through the unchanged `AgentService.prepare` path.
4. The server loads the stamped surface by `surfaceId` and confirms the named component declares that action. Unknown surface or action is `422`.
5. The server frames the action as untrusted data with `tools/framing.py::frame` and submits it as the turn's user message.
6. The run streams as a normal turn. A mutating tool still pauses for the native approval card.

### Design rules that fall out of this

- **Text first.** Every answer must be complete without its surface. Export, history, accessibility and non-rendering clients depend on it.
- **One direction of trust.** The model can propose UI; only the server can admit it.
- **Whole surfaces before streams.** Progressive rendering needs a new event and resumable streams. Both wait for Phase 4.

## 6. Major architectural decisions

These eight decisions are binding on implementation. They should be recorded as ADR 0015 in `docs/decisions/` (Proposed path) before any code is written, following the format of the existing 14 ADRs.

| # | Decision | Why | Rejected alternative |
| --- | --- | --- | --- |
| D1 | **A2UI v1.0 is the only UI payload format.** Pin the protocol version. Keep the dependency thin: validate with the published v1.0 JSON schemas; adopt `a2ui-core` only if gate G3 passes. | The spec is stable; the SDKs are not. A schema pin survives SDK churn. | The agent SDK and its Express inference format: adds an ANTLR runtime and prompt machinery Neuron does not need yet. |
| D2 | **Neuron's own stream and history carry A2UI.** No AG-UI, no A2A. Additive nullable fields; protocol version stays `1` until a new event is introduced. FastAPI path only; off by default behind a setting. | ADR 0010 decision 4 keeps the approval path free of protocol adapters. The A2UI transport contract is already met by SSE. | AG-UI binding: the path A2UI documents for LangGraph, but a second protocol on a security-critical path. |
| D3 | **The server is the only admitter of UI.** Every surface passes schema, catalog and limit validation before it is streamed or stored. Failure degrades to text; it never fails the run. | Neuron already rebuilds `used_tools` and validates citations server-side. UI follows the same rule. | Client-only validation: a non-Neuron client would then render unvalidated model output. |
| D4 | **A curated Neuron catalog, not the Basic catalog.** Phase 1: Text, Row, Column, List, Card, Tabs, Divider, Icon. Phase 2 adds Button, CheckBox, TextField, ChoicePicker, DateTimeInput, Slider. Never: Image, Video, AudioPlayer, Modal, `openUrl`. Text renders through Neuron's `Markdown.tsx`. | Media URLs are an exfiltration channel Neuron already blocks. Modal invites spoofing. The stock Markdown path injects HTML. | Stock Basic catalog with CSP as the only guard: weakens `img-src 'self'` or breaks at runtime. |
| D5 | **Approvals, sign-in and consent never render through A2UI.** Generated surfaces sit inside fixed, non-overridable chrome that labels them. No secret-type inputs exist in the catalog. | A model that can draw an approval dialog can phish one. The approval card stays the hand-written `ApprovalCard.tsx`. | Unifying approvals into A2UI forms for consistency. |
| D6 | **`AgentAnswer` stays flat. Model-authored UI enters through a tool.** The model never emits UI in the response format or in answer text. | The token extractor depends on a flat answer. A tool gives per-caller scoping, taint handling, timeouts and telemetry through `ToolSpec` for free. | A `ui` field on `AgentAnswer`; or fenced A2UI blocks parsed out of Markdown. |
| D7 | **Surfaces persist as a stamp on the stored answer.** Same mechanism as citations: `additional_kwargs` on the final `AIMessage`, validated again on read. No new table. Byte-capped. | Deletion, export, retention and ownership then apply with no new code paths. | A `surfaces` table: a second ownership model, which Neuron's assessment already flags as a weakness. |
| D8 | **A user action is an untrusted user turn.** It goes through `AgentService.prepare`, is checked against the stored surface, framed as data, and can never invoke a tool directly. | The action's shape was authored by the model and its values by the user; both are untrusted. Leases, budgets and approvals then apply unchanged. | A direct action-to-tool dispatch route: bypasses approval and taint rules. |

**Consequences.** Neuron gains one module, three response fields and, in Phase 2, one route. It does not gain a service, a table or a protocol. The cost is that progressive UI streaming and bidirectional function calls (`callRendererFunction`, `callAgentFunction`) are out of scope until Phase 4.

## 7. Feasibility, risks and security

The integration is feasible with small, additive changes on the server. The real uncertainty is on the client: whether an A2UI renderer can run under Neuron's CSP and lint rules without weakening either.

### Technical challenges and prerequisites

| Challenge | Detail | Resolution |
| --- | --- | --- |
| Renderer under strict CSP | `style-src 'self'`, no inline styles, no HTML injection. The Lit-based Basic catalog is unverified against this. | Gate G2. Fallback: a hand-written renderer for the Phase 1 subset (eight components), in the spirit of ADR 0010. |
| Dependency age and churn | 90-day rule; exact pins; `npm audit` clean. A2UI packages release about every two weeks with breaking changes. | Gate G3. Pin exact versions; upgrade deliberately, not continuously. |
| Tool results are not persisted | Surfaces built from tool artifacts must be composed inside the run, before the turn commits. | Compose in `_final_answer`, where citations are already resolved. |
| Flat structured output | No nested UI in `AgentAnswer`. | D6. |
| No resumable streams | A dropped stream loses progressive UI state. | Deliver whole surfaces in `final`; history is the source of truth. |
| Three oversized modules | `agent_service.py`, `api/main.py`, `models/factory.py` hold most behaviour and are security-critical. | Put new logic in the new module; touch the three files with the smallest possible edits. |
| Model reliability for Phase 3 | Whether the configured model emits valid catalog-bound trees is unknown. | Gate G4, measured with the existing eval harness. |

### Risk register

| Risk | Likelihood | Impact | Mitigation |
| --- | --- | --- | --- |
| UI spoofing: a surface imitates an approval, login or system message | Medium | High | D5: fixed chrome, no Modal, native approvals, no secret inputs. Security tests assert it. |
| Data exfiltration through media or links | Medium | High | D4: no media components, no `openUrl`; links only through `SafeLink`; CSP unchanged. |
| Injection through property values | Low | High | React elements only; Markdown through `Markdown.tsx`; lint already fails on `dangerouslySetInnerHTML`. |
| Layout denial of service | Medium | Medium | Server caps: components per surface, depth, bytes, string length, surfaces per answer. Client re-checks. |
| Prompt injection steers generated forms to harvest input | Medium | Medium | Tainted runs produce read-only surfaces; actions are framed as untrusted data (D8). |
| SDK churn breaks a release | High | Low | D1: depend on the schema, not the SDK. |
| A2UI loses momentum to MCP Apps | Low to medium | Medium | D2 and D3 keep A2UI behind one module; replacing the payload format touches the validator, catalog and renderer only. |
| Low user value: nothing worth rendering | Medium | Medium | Gate G1; Phase 1 limited to knowledge results; stop after Phase 1 if G1 metrics are not met. |
| Token and latency cost of model-authored UI | Medium | Low | Phase 3 only; budgeted through the existing token ledger; measured in G4. |

### Security requirements

1. **Authorization.** No new privileges. Rendering needs `agent:invoke` and `threads:read` as today. The UI tool gets its own `tools:render_ui` scope, so operators can withhold it per role.
2. **Taint.** A surface inherits the run's taint. On a tainted run, admit display components only; drop inputs and buttons.
3. **Identity.** Surfaces and actions never carry owner keys, tokens or raw subjects. Thread ownership is checked exactly as for approvals.
4. **Logging.** Telemetry records counts, component type names and rejection codes only. Never surface content, consistent with the audit schema.
5. **Output policy.** The system-prompt leak guard must also scan text properties of surfaces before they are admitted.
6. **Browser.** `scripts/web_headers.py` must not change. If the renderer needs a wider CSP, the renderer is wrong.
7. **Threat model.** Update `docs/security/threat-model.md` and `SECURITY.md` with a generated-UI section before Phase 1 ships.

### Alternatives compared

| Option | Model | Fit with Neuron | Verdict |
| --- | --- | --- | --- |
| A2UI v1.0 | Declarative JSON, client-owned catalog, native rendering | Strong on trust model; weak on SDK stability | Adopt as payload (this document) |
| [MCP Apps](https://modelcontextprotocol.io/seps/1865-mcp-apps-interactive-user-interfaces-for-mcp) | Server-supplied HTML in sandboxed iframes | Conflicts with text-only MCP results and with `frame-src` | Not now. Revisit if operators ask for third-party tool UIs |
| AG-UI | Agent-to-frontend event transport; carries A2UI | Already rejected in ADR 0010 | Not adopted; A2UI does not require it |
| [json-render](https://github.com/vercel-labs/json-render) and similar | Own JSON schema with Zod catalogs; has an A2UI adapter | Web-first, TypeScript server assumptions | No. Less portable than the format it adapts to |
| Neuron-native UI abstraction | A private typed-block schema in `final` | Cheapest first step; zero dependencies | No as a format, yes as a boundary: the hybrid keeps the private boundary and uses A2UI inside it |
| Status quo | Markdown only | No cost | The fallback if G1 fails |

A Neuron-native format would cost about the same server work as the hybrid, since validator, composers, stamping and renderer are needed either way. It would then need a migration when a second client or an MCP UI source appears. Choosing A2UI's schema now avoids that migration at the price of one schema pin.

## 8. GO / NO-GO decision

**CONDITIONAL GO. Weighted score 3.25 of 5 (65%). Confidence in the decision: 70%.**

An unconditional GO is not justified: user value today is modest and the client-side fit is unproven. A NO-GO is not justified either: the trust model fits, the server change is small and reversible, and the format choice avoids a later migration.

### Weighted assessment

| Criterion | Weight | Score (1 to 5) | Weighted | Basis |
| --- | --- | --- | --- | --- |
| Strategic fit and differentiation | 20% | 4.0 | 0.80 | Auditable generative UI extends Neuron's strongest trait |
| Security fit | 20% | 3.0 | 0.60 | Declarative model fits; stock renderer and catalog do not |
| User value now | 15% | 2.5 | 0.38 | One strong use case (knowledge results) |
| Technical compatibility | 15% | 3.5 | 0.53 | Additive on server; client unverified under CSP |
| Dependency maturity | 10% | 2.5 | 0.25 | Stable spec, 0.x libraries with frequent breaking changes |
| Implementation cost | 10% | 3.0 | 0.30 | One module, three fields, one route; renderer is the unknown |
| Reversibility | 10% | 4.0 | 0.40 | Off by default; isolated module; additive fields |
| **Total** | **100%** |  | **3.25** | Unrounded sum |

### Why 70% confidence

- **Raises it:** both codebases were read at source; the integration reuses a pattern Neuron already ships (citations); every phase can stop without rework.
- **Lowers it:** nothing was executed; renderer behaviour under Neuron's CSP is an assumption; model reliability for generated trees is unmeasured; A2UI adoption evidence is thin.

### Decision gates

Gates G1 to G3 are checked in the Phase 0 spike. Any failure there has a defined fallback, so the spike always ends in a decision.

| Gate | Question | Pass criterion | If it fails |
| --- | --- | --- | --- |
| G1 Use case | Is there something worth rendering? | Three named surfaces, each with an existing data source in Neuron, written into ADR 0015 | NO-GO. Stay on Markdown. |
| G2 Renderer | Does a renderer run under the unchanged production CSP, with no HTML-injection path and no lint exemption? | The Phase 1 catalog renders in the Playwright run under `scripts/web_headers.py` headers with zero CSP violations | Build the eight-component renderer by hand against the v1.0 schema. Still GO. |
| G3 Dependencies | Do the chosen packages pass Neuron's supply-chain rules? | `check_new_dependencies.py`, `check_new_npm_dependencies.py`, `pip-audit` and `npm audit` pass with exact pins | Vendor the v1.0 JSON schemas and validate with the existing `jsonschema` dependency. Still GO. |
| G4 Model reliability (before Phase 3) | Can the model author valid surfaces? | On a new eval suite: at least 95% valid on first attempt, at least 99% after one retry, zero invalid surfaces admitted | Phase 3 stays off. Server-composed surfaces continue. |
| G5 Security (before each phase ships) | Do the generated-UI threats have passing tests? | Spoofing, exfiltration, injection and limit tests pass in `tests/security/`; threat model updated | That phase does not ship. |

The G4 thresholds are proposed starting points, not measured values. Opus should confirm them against the baseline the eval harness produces.

## 9. Proposed roadmap

Five phases, each shippable and each able to be the last. No dates are proposed: Neuron's own roadmap is sequenced by release gates, and v1.2.0 (RAG-E09) is already a proposal competing for the same owner.

| Phase | Scope | Depends on | Success criteria |
| --- | --- | --- | --- |
| 0. Decide | ADR 0015; spike for G1, G2, G3; threat-model draft. No production code. | Nothing | Three surfaces named; renderer choice made; dependency choice made; ADR accepted |
| 1. Show | Read-only, server-composed surfaces for knowledge results. Fields on `final`, `/invoke` and history. Web renderer for eight display components. Off by default. | Phase 0; G5 | With the flag off, responses are byte-identical to today. With it on, surfaces survive reload from history; zero CSP violations; contract test updated and green |
| 2. Interact | Input components; action route; clarification forms composed by the server when `clarification_needed` is set. | Phase 1; G5 | An action round trip completes as a normal leased, budgeted turn; forged surface or action IDs return `422`; tainted runs show no inputs |
| 3. Generate | `render_ui` tool; model-authored trees; validation retry; eval suite; operator scope. | Phase 2; G4; G5 | G4 thresholds met on the nightly eval; rejected surfaces never reach clients; token overhead reported per run |
| 4. Extend | Progressive `surface` stream event (protocol version 2); `updateDataModel` for live dashboards; A2UI from pinned MCP servers; a second renderer. | Phase 3; durable or resumable runs; ADR 0009 amendment for non-text MCP content | Each item gets its own ADR. None is committed by this document |

**Priority against Neuron's other work.** Phases 0 and 1 are small and can run beside v1.2.0. Phases 3 and 4 should follow, not precede, the platform gaps Neuron's assessment lists (durable runs, dynamic tools), because they are what gives generated UI something to show.

## 10. Prioritized engineering handoff

Start with the ADR and the spike; write no feature code until the three Phase 0 gates have an answer. The order below is the order of work.

| Priority | Work item | Phase | Output |
| --- | --- | --- | --- |
| P0 | Write ADR 0015 from section 6; name the three G1 surfaces | 0 | `docs/decisions/0015-generated-ui.md` (Proposed) |
| P0 | Renderer spike under production CSP (G2) | 0 | A recorded result and a renderer choice in the ADR |
| P0 | Dependency check for `a2ui-core`, `@a2ui/react`, `@a2ui/web_core` (G3) | 0 | Pass or the vendored-schema fallback, recorded in the ADR |
| P0 | Generated-UI section in the threat model | 0 | `docs/security/threat-model.md` updated |
| P1 | Catalog, validator, limits, settings flag | 1 | `presentation/` module with unit and security tests |
| P1 | Knowledge-results composer and answer stamping | 1 | Surfaces in `final`, `/invoke`, history |
| P1 | Web parser, state, renderer, chrome | 1 | `features/surfaces/` and updated stream contract |
| P1 | Telemetry names and metrics | 1 | Entries in `semconv.py` and `metrics.py` only |
| P2 | Action route, action validation, framing | 2 | One route, security tests for forged actions |
| P2 | Input components; clarification-form composer | 2 | Catalog v1.1 of the Neuron catalog |
| P3 | `render_ui` tool, prompt rules, retry, eval suite | 3 | Tool in registry behind scope; G4 report |
| P4 | Stream event, live updates, MCP UI, second renderer | 4 | One ADR each |

Everything Opus needs to act on these items is in section 11.

## 11. Implementation Blueprint for Claude Opus

This section is self-contained. It assumes the decisions in section 6 and does not repeat their rationale. Paths are relative to the repository root at commit `0f78ef9`. **Verified** paths exist today. **Proposed** paths do not.

Read first, in this order: `CLAUDE.md`, `AGENTS.md`, `ARCHITECTURE.md`, ADRs 0005, 0009, 0010 and 0014 in `docs/decisions/`, then `SECURITY.md`. They set conventions this blueprint relies on.

### 11.1 Existing components to reuse (Verified)

| Path | Reuse for |
| --- | --- |
| `src/neuron_agent/knowledge/citations.py` | The reference pattern. Server validates model claims against run messages, then the graph stamps the result on the answer. Surfaces copy this shape. |
| `src/neuron_agent/graphs/main_graph.py` (`_final_answer`, `_run_stamp`, `_guard_answer`, `agent_node`) | Where citations are resolved and stamped. Surfaces are composed and stamped at the same point. |
| `src/neuron_agent/schemas/agent.py` (`CitationFields`, `AgentResponse`, `ThreadMessage`) | The mixin pattern for additive nullable response fields. |
| `src/neuron_agent/services/agent_service.py` (`_response`, `_stamped_citations`, `_public_thread_messages`, `prepare`, `prepare_decision`, `stream`) | Response assembly, history projection and the prepared-run path that any new route must use. |
| `src/neuron_agent/api/main.py` (`stream_approval_decision`, `_stream_prepared`, `require_permission`) | The template for a thread-scoped streamed route. |
| `src/neuron_agent/tools/registry.py` (`ToolSpec`, `ToolRegistry`) | Registration, scope, risk and taint for the Phase 3 tool. |
| `src/neuron_agent/tools/framing.py` (`frame`) | Wrapping untrusted action data as one escaped block. |
| `src/neuron_agent/knowledge/tools.py` | Knowledge tools return `content_and_artifact`; the artifact is the trusted input for the first composer. |
| `src/neuron_agent/security/output_policy.py` | Leak guard to apply to surface text. |
| `src/neuron_agent/security/authorization.py` (`AuthorizationContext`) | Per-run permissions; read for the tool scope. Do not add UI state to it. |
| `src/neuron_agent/config/settings.py` | Feature flag and limits, `APP_` prefix, validated like `knowledge_enabled`. |
| `src/neuron_agent/observability/semconv.py`, `metrics.py`, `audit.py` | The only places telemetry names and audit fields may be defined. |
| `src/neuron_agent/errors/base.py` | `AppError` taxonomy for the action route's failures. |
| `web/src/lib/stream/citations.ts`, `events.ts`, `state.ts`, `contract.json` | The pattern for parsing additive fields with runtime checks. |
| `web/src/features/chat/Markdown.tsx` (`Markdown`, `SafeLink`) | The only Markdown and link renderer surfaces may use. |
| `web/src/features/chat/chatState.ts`, `useChat.ts`, `history.ts`, `ChatScreen.tsx`, `Sources.tsx` | Message state, send path, history mapping and where a surface mounts beside sources. |
| `web/src/components/ui/*` (card, button, input, textarea, badge, alert) | The visual primitives catalog components wrap. |
| `tests/unit/test_web_stream_contract.py` | Must be extended with every wire change. |
| `tests/security/test_import_boundaries.py` | Must learn the new module's allowed imports. |

### 11.2 Modules likely to change (Verified paths)

| Path | Change | Phase |
| --- | --- | --- |
| `src/neuron_agent/schemas/agent.py` | Add a surface-fields mixin beside `CitationFields`; apply to `AgentResponse` and `ThreadMessage`. Do not touch `AgentAnswer` or `AgentRequest`. | 1 |
| `src/neuron_agent/graphs/main_graph.py` | Call the composer and validator after citation validation; stamp the result. Keep the edit to a few lines. | 1 |
| `src/neuron_agent/services/agent_service.py` | Read the stamp in `_response` and in history projection; add `prepare_action` in Phase 2. | 1, 2 |
| `src/neuron_agent/config/settings.py` | `APP_UI_ENABLED` (default false) and limit settings; refuse it on configurations that cannot persist answers. | 1 |
| `src/neuron_agent/api/main.py` | One new route in Phase 2. No change in Phase 1. | 2 |
| `src/neuron_agent/observability/semconv.py`, `metrics.py` | Counters for surfaces admitted, surfaces rejected by code, actions received. | 1, 2 |
| `src/neuron_agent/prompts/system/main.md` | Rules for the UI tool. Phase 3 only. | 3 |
| `src/neuron_agent/services/agent_service.py` (`_compose_tools`) | Register the UI tool on the FastAPI path only, as memory and knowledge tools are. | 3 |
| `src/neuron_agent/evaluation.py`, `tests/evals/` | A generated-UI suite for G4. | 3 |
| `web/src/lib/stream/events.ts`, `contract.json`, `state.ts` | Parse and carry the new fields. | 1 |
| `web/src/features/chat/chatState.ts`, `history.ts`, `ChatScreen.tsx`, `useChat.ts` | Hold surfaces on `ChatMessage`; mount the renderer; send actions in Phase 2. | 1, 2 |
| `web/package.json` | Renderer packages, only if G2 and G3 pass. Exact versions. | 1 |
| `pyproject.toml`, `uv.lock` | `a2ui-core`, only if G3 passes. | 1 |
| `ARCHITECTURE.md`, `SECURITY.md`, `OPERATIONS.md`, `CHANGELOG.md`, `docs/ROADMAP.md`, `docs/security/threat-model.md` | Document as built, as every prior release did. | Each |
| `scripts/web_headers.py` | **Must not change.** | Never |

### 11.3 New components (Proposed paths)

| Path | Responsibility | Must not |
| --- | --- | --- |
| `src/neuron_agent/presentation/__init__.py` | Package marker with the house licence header. |  |
| `src/neuron_agent/presentation/catalog.py` | Load and expose the Neuron catalog and its `catalogId`; list allowed components and functions per phase. | Import from `models`, `graphs` or `services`. |
| `src/neuron_agent/presentation/catalog/neuron_v1.json` | The catalog definition, conforming to A2UI `catalog_definition.json`. Shipped in the wheel (see `source-include` in `pyproject.toml`). | Reference a remote schema. |
| `src/neuron_agent/presentation/validation.py` | Validate a list of A2UI messages: envelope schema, catalog membership, reference integrity (`root` exists, children resolve, no cycles), Neuron limits, tainted-run restrictions, leak guard on text. Return admitted surfaces or stable rejection codes. | Raise on invalid input, echo payload text in errors or logs, resolve remote `$ref`. |
| `src/neuron_agent/presentation/composers.py` | Pure functions from trusted inputs (resolved citations, tool artifacts) to A2UI messages. First composer: knowledge sources. | Read model-authored text for structure. |
| `src/neuron_agent/presentation/surfaces.py` | Stamp admitted surfaces on an `AIMessage`; read and re-validate a stamp; enforce the byte cap. | Store anything outside `additional_kwargs`. |
| `src/neuron_agent/presentation/actions.py` (Phase 2) | Validate an inbound action against a stamped surface; produce the framed user message. | Dispatch tools. |
| `src/neuron_agent/presentation/tool.py` (Phase 3) | Build the `render_ui` `ToolSpec`. Validate arguments; return a short fixed acknowledgement; hand the admitted surface to the run for stamping. | Return the payload to the model as tool output. |
| `src/neuron_agent/schemas/ui.py` | Pydantic models for the wire fields and the action request body (`extra="forbid"`). |  |
| `web/src/lib/stream/surfaces.ts` | Runtime-checked parser for the surface fields, modelled on `citations.ts`. | Accept unknown component types. |
| `web/src/features/surfaces/SurfaceView.tsx` | Fixed chrome plus the rendered surface. | Render when the payload fails client checks. |
| `web/src/features/surfaces/catalog/` | One React component per catalog entry, built on `components/ui`. | Use `dangerouslySetInnerHTML`, inline styles, images or raw anchors. |
| `web/src/features/surfaces/actions.ts` (Phase 2) | Build and post the A2UI `action`. | Put identifiers in query strings. |
| `docs/decisions/0015-generated-ui.md` | The ADR. |  |
| `tests/unit/test_presentation_*.py`, `tests/security/test_generated_ui.py`, `tests/graph/`, web `*.test.tsx`, `web/e2e/surfaces.spec.ts` | See 11.11. |  |

### 11.4 Component boundaries

- `presentation/` may import `schemas`, `errors`, `config`, `observability`, `security.output_policy` and `tools.framing`. It must not import `models`, `graphs`, `services`, `api` or `knowledge`. Composers receive plain data, so `knowledge` stays unaware of UI.
- `graphs/` calls `presentation` at one point, as it calls `knowledge/citations.py` today.
- `web/src/features/surfaces` depends on `lib/stream` types and `components/ui`. `features/chat` mounts it; it does not import chat internals.
- If `@a2ui/react` is adopted, it is imported only inside `features/surfaces`. Nothing else may reference A2UI packages, so the fallback renderer stays a drop-in.

### 11.5 Data and interaction flows

The render flow and action flow in section 5 are the required flows. Three additions for implementation:

- **Composition point.** Compose after `citations.validate` returns and before `_guard_answer` runs, so the leak guard and the stamp see the final surface.
- **Phase 3 flow.** The model calls `render_ui`. The tool validates, keeps the admitted surface in run-local state and returns a fixed acknowledgement. `_final_answer` collects admitted surfaces from the run's tool messages, as it collects citations. On rejection the tool returns the standard A2UI validation error shape (`VALIDATION_FAILED`, JSON pointer, one sentence) so the model can retry once.
- **Only the newest surface is interactive.** The server accepts an action only for a surface on the thread's most recent assistant turn. The client disables controls on older surfaces.

### 11.6 API and protocol requirements

| Topic | Requirement |
| --- | --- |
| A2UI version | Every envelope carries `"version": "1.0"`. Reject anything else. |
| Surface shape, Phases 1 to 3 | Exactly one `createSurface` per surface, with `components` and `dataModel` embedded (v1.0 single-message instantiation). No `updateComponents`, `updateDataModel` or `deleteSurface` yet. No `theme` (invalid in v1.0). |
| `surfaceId` | Server-minted UUID. In Phase 3, replace whatever the model supplied. The spec requires uniqueness for the renderer's lifetime. |
| `catalogId` | The Neuron catalog's identifier, a stable string in URI form. It need not resolve. |
| Functions | Phase 1: formatting functions only (`formatString`, `formatNumber`, `formatDate`, `pluralize`). Phase 2 adds validation functions (`required`, `length`, `numeric`, `email`, `and`, `or`, `not`). `regex` and `openUrl` stay out. |
| Bidirectional calls | `callRendererFunction`, `callAgentFunction` and their responses are not implemented. Reject them. |
| Wire fields | `surfaces`, `surface_schema_version`, `a2ui_version` on `AgentResponse`, the `final` event and `ThreadMessage`. Null unless a surface exists. |
| Events | Unchanged in Phases 1 to 3. `STREAM_PROTOCOL_VERSION` stays `"1"`. |
| Action route (Phase 2, Proposed) | `POST /v1/threads/{thread_id}/surface-actions/stream`. Body: one A2UI v1.0 `action` object plus the optional `knowledge_base_ids` the approvals body already carries. Response: the same event stream as `/v1/agent/stream`. |
| Action errors | Missing or foreign thread: `404 thread_not_found`. Run in flight: `409 thread_busy`. Unknown surface, undeclared action, stale surface or oversized context: `422`. Use existing `AppError` classes; add none unless required. |
| Limits (proposed starting values, as settings) | 3 surfaces per answer; 100 components and depth 8 per surface; 32 KB per surface; 64 KB per answer stamp; 2,000 characters per string; 4 KB per action context. |
| Capability negotiation | Not implemented. One first-party client and one catalog. Record it as an open question for a second client. |

### 11.7 Backend and frontend responsibilities

| Concern | Backend | Frontend |
| --- | --- | --- |
| Validation | Authoritative. Schema, catalog, limits, taint, leak guard. | Defensive re-check of shape, known components and limits. Invalid means show text only. |
| Layout decisions | Composers (Phases 1, 2); model through the tool (Phase 3). | None. Renders what it is given. |
| Styling | None. A2UI v1.0 carries no theme. | Neuron's Tailwind tokens and `components/ui`. Light and dark themes via `lib/theme.ts`. |
| Text content | Plain strings and Markdown source. | `Markdown.tsx` only. |
| Identity and ownership | Owner check on every read and every action. | Sends the bearer token; holds nothing else. |
| Action handling | Verifies against the stored surface; frames; runs a turn. | Builds the `action`; one in flight at a time; disables stale surfaces. |
| Accessibility | Supplies labels in composers. | Meets the existing axe checks (`web/src/test/axe.ts`); keyboard reachable; chrome announces generated content. |
| Failure | Drop the surface, keep the answer, count and log the code. | Show the answer; never show an error for a surface alone. |

### 11.8 Security and authorization requirements

1. **Permissions.** Surfaces in responses need no new permission. The action route requires `agent:invoke`. The Phase 3 tool has scope `tools:render_ui`, risk `read`, source `builtin`, `taints_run=False`.
2. **Ownership.** The action route resolves the thread through the same owner check as `prepare_decision`. Foreign and missing threads are indistinguishable.
3. **Taint.** Use the existing taint signal (`is_tainted` in `models/factory.py` and the taint stamp on stored answers). On a tainted run, admit display components only.
4. **Untrusted action data.** Validate the action against the stored surface, cap its size, then wrap it with `frame`. The result is the turn's `user_message` and passes `validate_user_message` like any other.
5. **No direct effects.** An action can only start a turn. Mutating tools still interrupt for approval through `HumanInTheLoopMiddleware`.
6. **No secrets in UI.** The catalog has no password or hidden input. Composers never place tokens, owner keys or raw subjects in a data model.
7. **Spoof resistance.** Chrome is rendered by the client outside the surface tree and cannot be styled or removed by a payload. The approval card stays `ApprovalCard.tsx`.
8. **Links and media.** No media components. Any URL rendered goes through `SafeLink`.
9. **Telemetry.** Names, counts and codes only. Add a case to `tests/security/test_telemetry_leaks.py`.
10. **Limits.** The action route sits under the existing rate limiter and body-size middleware, like every `/v1/threads/*` route.

### 11.9 Streaming and persistence

- **Streaming, Phases 1 to 3.** No change to `AnswerTokenExtractor`, `StreamLeakGuard` or `_produce` beyond passing the stamped fields into `final`. Token deltas stay a text-only preview. A `render_ui` call appears as an ordinary `tool_call` event with its name.
- **Streaming, Phase 4.** A new `surface` event needs a protocol version bump and a contract fixture update. The client already ignores unknown events, so older clients keep working.
- **Persistence.** The stamp lives in `additional_kwargs` of the final `AIMessage`, next to `citations`. It is written in the same atomic turn commit. A failed run stores nothing.
- **Read path.** Validate the stamp again when reading (as `_stamped_citations` does); drop it silently if invalid and log `stored_surfaces_invalid`.
- **Lifecycle.** Thread deletion, retention pruning, turn eviction and bulk erase remove surfaces with their message. Export returns them through `ThreadMessage`, inside the existing export byte cap.
- **Size.** Every checkpoint holds the whole thread, so the per-answer cap bounds checkpoint growth. Do not raise it without measuring.

### 11.10 Backward compatibility

- With `APP_UI_ENABLED=false`, every response, event and stored message is byte-identical to v1.1.0. A test must prove it.
- With the flag turned off after use, stored stamps are ignored on read. Rollback is the flag.
- Old clients ignore the new fields. New clients treat absent fields as no surface.
- Threads created before the feature have no stamp and render as today.
- `/v1/agent/invoke` and `/v1/agent/stream` requests are unchanged. `AgentRequest` keeps `extra="forbid"`.
- The Agent Server path (`langgraph.json`) never produces surfaces and never registers the UI tool.
- No database migration in any of Phases 1 to 3.

### 11.11 Implementation sequence and dependencies

Each step depends on the ones above it. Steps inside a milestone can be separate pull requests.

1. **M0 Decision.**
   1. Write ADR 0015 with the three named surfaces (G1).
   2. Run the renderer spike under production headers (G2). Record the outcome and the renderer choice.
   3. Run the dependency checks (G3). Record the validator choice: `a2ui-core` or vendored schemas.
   4. Draft the threat-model section.
2. **M1 Server foundation.**
   1. Settings flag and limits.
   2. `schemas/ui.py` and the response mixin.
   3. Catalog file and loader.
   4. Validator with limits and rejection codes.
   5. Telemetry names and metrics.
   6. Import-boundary test update.
3. **M2 First surface end to end.**
   1. Knowledge-sources composer.
   2. Composition and stamping in the graph.
   3. Response and history projection in `AgentService`.
   4. Contract fixture and contract test.
4. **M3 Web rendering.**
   1. `lib/stream/surfaces.ts` parser and state.
   2. Catalog components and `SurfaceView` chrome.
   3. Mount in chat and in reopened threads.
   4. Playwright run under CSP.
   5. Documentation as built. Phase 1 ships here.
5. **M4 Interaction (Phase 2).**
   1. Input components in catalog, validator and renderer.
   2. `presentation/actions.py` and `AgentService.prepare_action`.
   3. The action route.
   4. Client action dispatch and stale-surface handling.
   5. Clarification-form composer.
6. **M5 Generation (Phase 3).**
   1. `render_ui` tool and registration.
   2. Prompt rules and one-retry behaviour.
   3. Eval suite and G4 report.
   4. Operator documentation for the scope.

### 11.12 Acceptance criteria per milestone

| Milestone | Accepted when |
| --- | --- |
| M0 | ADR 0015 is merged as Accepted. It names three surfaces, the renderer, the validator and the fallback taken, if any. No file under `src/` or `web/src/` changed. |
| M1 | The validator admits the reference fixtures and rejects each negative fixture with the expected code. With the flag off, the full existing suite passes unchanged. `ruff`, `mypy`, `bandit` and the import-boundary test are green. |
| M2 | A knowledge-grounded answer returns one surface in `/invoke`, in `final` and in thread history, identical in all three. An ungrounded answer returns nulls. A rejected surface leaves the answer intact and increments the rejection counter. The contract test is green. |
| M3 | The surface renders in the browser and after reload. The Playwright run under `scripts/web_headers.py` headers reports zero CSP violations. Axe checks pass. ESLint passes with no new exemptions. Old-client behaviour is covered by a test that ignores the new fields. |
| M4 | A button or form action completes a turn with a lease and a budget reservation. Forged `surfaceId`, undeclared action, stale surface, foreign thread and oversized context are each refused with the specified status. On a tainted run no input component is admitted. A mutating tool reached through an action still shows the native approval card. |
| M5 | The tool is invisible to callers without `tools:render_ui`. G4 thresholds are met on the eval suite with the configured model. No invalid surface is admitted in any eval run. Per-run token overhead is reported. |

### 11.13 Testing and validation requirements

| Layer | Location | What to cover |
| --- | --- | --- |
| Unit, Python | `tests/unit/` (Verified dir) | Validator: schema, catalog membership, reference integrity, cycles, every limit, version check, rejected message types. Composers: deterministic output for fixed input. Stamping: round trip, byte cap, invalid stamp dropped. |
| Graph | `tests/graph/` (Verified dir) | Surface stamped only on success; nothing stored on a failed run; flag off equals baseline. |
| Security | `tests/security/` (Verified dir) | Spoofing attempts (approval-like text, excluded components), media and `openUrl` rejection, property-value injection, limit exhaustion, taint restriction, action forgery, cross-user isolation, telemetry leak check. |
| Contract | `tests/unit/test_web_stream_contract.py` (Verified) | New fields in the `final` fixture; event list unchanged in Phases 1 to 3. |
| Integration | `tests/integration/` (Verified dir) | Postgres checkpoint round trip of a stamped answer; export and erase include and remove surfaces. |
| Evals | `tests/evals/`, `src/neuron_agent/evaluation.py` (Verified) | Phase 3 suite: validity rate, retry recovery, catalog adherence, refusal to draw approval-like UI when prompted. |
| Web unit | `web/src/**/*.test.tsx` (Verified pattern) | Parser accepts valid and rejects malformed payloads; each catalog component; chrome always present; unknown component renders nothing. |
| Web end to end | `web/e2e/` (Verified dir) | Surface visible under production CSP; reload; action round trip in Phase 2. |
| Reference fixtures | Proposed: `tests/fixtures/ui/` | Valid and invalid A2UI v1.0 messages. Seed the valid set from A2UI's own `specification/v1_0/test` cases where the licence header is kept. |

Existing gates still apply: mutation testing, CodeQL, DAST, dependency review and the 90-day dependency checks in `.github/workflows/`.

### 11.14 Known risks and unresolved technical questions

These are open. Opus should resolve each in ADR 0015 or in the pull request that first touches it.

- [ ] **Renderer choice (G2).** Does `@a2ui/react` with a Neuron-only catalog and `MarkdownComponentContext` run under `style-src 'self'` with no reachable `unsafeHTML` path? If not, hand-write the renderer.
- [ ] **Bundle cost.** What does `@a2ui/web_core` add to the built bundle after tree-shaking, given it depends on `lit`? Not measured.
- [ ] **Validator choice (G3).** Does `a2ui-core` pass the 90-day rule and `pip-audit`, and are its added dependencies (`babel`, `regex`) acceptable? If not, vendor the v1.0 JSON schemas.
- [ ] **Schema validator safety.** Neuron's MCP client refuses remote `$ref` and server-written regex. The A2UI schemas must be loaded with the same local-only registry.
- [ ] **Do stamps reach the model?** Confirm that `additional_kwargs` stamps are not serialised into provider requests, or strip them in `bound_model_history`. Citations set the precedent; verify rather than assume.
- [ ] **What the model sees of a prior surface.** After an action, should the framed turn include a compact description of the surface? Needed for coherent follow-ups; costs tokens.
- [ ] **`sendDataModel` for forms.** Should form values return in the action `context` only, or as the surface data model in metadata? Context only is simpler and is the recommended start.
- [ ] **Non-stream action route.** Approvals have both a JSON and a stream route. Is parity needed for actions?
- [ ] **Idempotency.** Neuron has no idempotency key on runs. A double-submitted action can create two turns once the first finishes. Accept, or add a key.
- [ ] **Catalog versioning.** How does a stored surface render after the catalog changes? Recommended: version the `catalogId`; the client keeps renderers for old versions or falls back to text.
- [ ] **Capability negotiation.** A second client will need the A2UI renderer-capabilities exchange. Out of scope until one exists.
- [ ] **G4 thresholds.** 95% and 99% are proposals. Set them from a measured baseline.
- [ ] **Module size.** Edits to `agent_service.py`, `api/main.py` and `models/factory.py` add to files Neuron's own assessment calls too large. Keep each edit minimal; do not refactor them in this work.

## 12. Sources and method

Both repositories were cloned and read at source on 2026-11-12. Package versions were read from the npm and PyPI registries the same day. No tests, builds or model calls were run, and no file in either repository was changed.

**Neuron** ([Md-Nisar/neuron](https://github.com/Md-Nisar/neuron), commit `0f78ef9`)

- [`ARCHITECTURE.md`](https://github.com/Md-Nisar/neuron/blob/main/ARCHITECTURE.md), [`SECURITY.md`](https://github.com/Md-Nisar/neuron/blob/main/SECURITY.md), [`docs/ROADMAP.md`](https://github.com/Md-Nisar/neuron/blob/main/docs/ROADMAP.md)
- [`NEURON_CURRENT_ARCHITECTURE_ASSESSMENT.md`](https://github.com/Md-Nisar/neuron/blob/main/research/enterprise-strategy/architecture/NEURON_CURRENT_ARCHITECTURE_ASSESSMENT.md)
- [ADR 0010, User Application](https://github.com/Md-Nisar/neuron/blob/main/docs/decisions/0010-user-application.md)
- Source: [`schemas/agent.py`](https://github.com/Md-Nisar/neuron/blob/main/src/neuron_agent/schemas/agent.py), [`services/streaming.py`](https://github.com/Md-Nisar/neuron/blob/main/src/neuron_agent/services/streaming.py), [`services/agent_service.py`](https://github.com/Md-Nisar/neuron/blob/main/src/neuron_agent/services/agent_service.py), [`graphs/main_graph.py`](https://github.com/Md-Nisar/neuron/blob/main/src/neuron_agent/graphs/main_graph.py), [`models/factory.py`](https://github.com/Md-Nisar/neuron/blob/main/src/neuron_agent/models/factory.py), [`tools/registry.py`](https://github.com/Md-Nisar/neuron/blob/main/src/neuron_agent/tools/registry.py), [`tools/mcp/client.py`](https://github.com/Md-Nisar/neuron/blob/main/src/neuron_agent/tools/mcp/client.py), [`tools/framing.py`](https://github.com/Md-Nisar/neuron/blob/main/src/neuron_agent/tools/framing.py), [`api/main.py`](https://github.com/Md-Nisar/neuron/blob/main/src/neuron_agent/api/main.py)
- Web: [`lib/stream/events.ts`](https://github.com/Md-Nisar/neuron/blob/main/web/src/lib/stream/events.ts), [`features/chat/Markdown.tsx`](https://github.com/Md-Nisar/neuron/blob/main/web/src/features/chat/Markdown.tsx), [`features/chat/chatState.ts`](https://github.com/Md-Nisar/neuron/blob/main/web/src/features/chat/chatState.ts), [`web/package.json`](https://github.com/Md-Nisar/neuron/blob/main/web/package.json)
- Policy and tests: [`scripts/web_headers.py`](https://github.com/Md-Nisar/neuron/blob/main/scripts/web_headers.py), [`scripts/check_new_npm_dependencies.py`](https://github.com/Md-Nisar/neuron/blob/main/scripts/check_new_npm_dependencies.py), [`tests/unit/test_web_stream_contract.py`](https://github.com/Md-Nisar/neuron/blob/main/tests/unit/test_web_stream_contract.py)

**A2UI** ([a2ui-project/a2ui](https://github.com/a2ui-project/a2ui), commit `8bf644a`)

- [Protocol specification v1.0](https://a2ui.org/specification/v1.0-a2ui/) and its [repository source](https://github.com/a2ui-project/a2ui/blob/main/specification/v1_0/docs/a2ui_protocol.md)
- [`specification/versions.json`](https://github.com/a2ui-project/a2ui/blob/main/specification/versions.json), [v1.0 README](https://github.com/a2ui-project/a2ui/blob/main/specification/v1_0/README.md)
- [Official roadmap](https://a2ui.org/roadmap/), [repository README](https://github.com/a2ui-project/a2ui/blob/main/README.md)
- [React renderer README](https://github.com/a2ui-project/a2ui/blob/main/typescript/renderers/react/README.md) and [changelog](https://github.com/a2ui-project/a2ui/blob/main/typescript/renderers/react/CHANGELOG.md)
- [`web_core` Markdown directive](https://github.com/a2ui-project/a2ui/blob/main/typescript/core/web_core/src/universal/basic_catalog/directives/markdown.ts)
- [`a2ui-core` changelog](https://github.com/a2ui-project/a2ui/blob/main/python/a2ui_core/CHANGELOG.md), [agent SDK README](https://github.com/a2ui-project/a2ui/blob/main/python/a2ui_agent/README.md)
- Guides: [agent integration](https://github.com/a2ui-project/a2ui/blob/main/docs/site/src/content/docs/guides/agent-integration.mdx), [any agent framework](https://github.com/a2ui-project/a2ui/blob/main/docs/public/guides/a2ui-with-any-agent-framework.md), [A2UI over MCP](https://github.com/a2ui-project/a2ui/blob/main/docs/site/src/content/docs/guides/a2ui-over-mcp.mdx), [community renderers](https://github.com/a2ui-project/a2ui/blob/main/docs/site/src/content/docs/ecosystem/renderers.mdx)
- Registries: [@a2ui/react](https://www.npmjs.com/package/@a2ui/react), [@a2ui/web\_core](https://www.npmjs.com/package/@a2ui/web_core), [a2ui-core](https://pypi.org/project/a2ui-core/), [a2ui-agent-sdk](https://pypi.org/project/a2ui-agent-sdk/)

**Third-party context**

- [InfoQ: Google A2UI, July 2026](https://infoq.com/news/2026/07/google-a2ui-genui)
- [The New Stack: MCP Apps and A2UI](https://thenewstack.io/agent-ui-standards-multiply-mcp-apps-and-googles-a2ui/)
- [MCP SEP-1865, MCP Apps](https://modelcontextprotocol.io/seps/1865-mcp-apps-interactive-user-interfaces-for-mcp) (listed in search results; not opened)

**Limits of this assessment.** The a2ui.org home and renderer reference pages could not be fetched; the repository's copies of the same documentation were read instead. Claims about runtime behaviour of the A2UI renderer under Neuron's CSP are assumptions until gate G2 runs.
