# Chart Generation Decision and Handoff (Flint and alternatives)

| | |
| --- | --- |
| Date | 2026-11-12 |
| Status | Research proposal. No code, configuration or ADR changes. |
| Question | Should Neuron adopt Microsoft's Flint for charts in data answers, use an alternative, or combine them? Where does it sit on the roadmap? |
| Companion | `STRUCTURED_DATA_DECISION_AND_HANDOFF.md` (the Data Gateway decision, proposed separately). This document depends on it. |
| Evidence | **VERIFIED** = read in the named source on the date above. **INFERRED** = my reasoning or background knowledge not re-read. **UNKNOWN** = could not be established. Nothing was installed or run. |

## 1. Executive summary

- **Verdict: adopt Flint later, as the first optional renderer.** About 75% confidence. There is nothing to chart until the Data Gateway returns rows.
- **Approach: a neutral chart contract owned by Neuron, with swappable renderers in the web app.** The chart spec names a `query_id` and column names, never data values. The server validates it and the browser joins it to the rows it already holds.
- **Start with rules, not the model.** Pick the default chart from column roles (time plus measure gives a line). Let the model propose charts only after a spike shows it beats the rules.
- **Skip `flint-chart-mcp`.** Its local server is stdio-only; Neuron's MCP client speaks only Streamable HTTP.
- **Top risks:**
  1. Flint is four and a half months old and still breaking its interfaces.
  2. Its measured quality edge is small and judged by a model, and it ties on simple bar charts, which is most of analytics.
  3. Rendering untrusted labels through a Vega stack that had several expression XSS advisories in 2025.

What would change the verdict: Flint failing either spike in section 8 (then use a hand-mapped renderer); or the gateway failing its own proof (then no charts at all).

## 2. Findings

### 2.1 Flint

| Claim | Tag |
| --- | --- |
| MIT licence; 4.6k stars; 267 forks; 28 open issues; 855 commits | VERIFIED (repository page) |
| First release 0.1.1 on 28 June 2026; blog post 8 July; paper submitted 22 July; 0.4.0 on 24 July; 1.0.0 on 19 October; 1.0.1 on 21 October | VERIFIED (`CHANGELOG.md`, blog, arXiv). Sources that disagree on version are describing different months. |
| Spec is JSON: data, semantic types, chart type and encodings, optional theme and interaction specs | VERIFIED (README) |
| 52 chart types, 14 themes, 23 interaction presets; compiles to Vega-Lite, ECharts, Chart.js, Plotly and native Excel charts | VERIFIED (README) |
| Themes apply to Vega-Lite and Plotly output only; ECharts, Chart.js and Excel ignore them | VERIFIED (`docs/theme-spec.md`) |
| Browser rendering through a React component (`flint-chart/react`) and vanilla APIs; static SVG through `flint-chart/render` | VERIFIED (README, CHANGELOG) |
| Python port is a source preview, not released | VERIFIED (README) |
| MCP tools were reworked in 1.0.0, and an unreleased change makes the server stateless and removes more tools | VERIFIED (`CHANGELOG.md`) |
| Local MCP server supports stdio only; a hosted endpoint is named at `flint.data-formulator.ai/mcp` | VERIFIED (MCP README); the endpoint was not tested |
| The MCP `show` tool returns an interactive card that needs a host supporting MCP Apps | VERIFIED (MCP README) |
| Limits: `maxDataRows` default 100,000; `maxCanvasDim` default 4,000; remote data URLs are never fetched | VERIFIED (`docs/api-reference.md`, MCP README) |
| Open issue #129: some theme and ECharts values reach SVG output unescaped | VERIFIED (issue list) |
| Open issue #155: the React build fails unless every optional backend is installed | VERIFIED (issue list) |
| Open issue #68: `validate_chart` silently accepts unknown property keys | VERIFIED (issue list) |
| Evaluation: 315 questions on 63 TidyTuesday tables; Flint 16.27 against direct Vega-Lite 15.91 out of 20 on GPT-5.1; pairwise wins 41% to 38% | VERIFIED (blog; paper HTML, partly tool-summarised) |
| In that study bar charts tied and boxplots lost; the grader was the same model family that wrote the questions | VERIFIED (paper, tool-summarised) |
| No published token, latency or failure-rate numbers; no comparison against ECharts or code generation | VERIFIED (absent from blog and paper) |
| Accessibility is tracked as an open issue, with no documented support | VERIFIED (author reply on Hacker News; no section in docs) |
| npm download numbers; the full semantic-type list | UNKNOWN (npm returned 403; the docs site is client-rendered and was unreadable) |

Community reception (Hacker News, 350 points, 137 comments, VERIFIED): praise for semantic types and automatic layout; criticism that Vega-Lite already does this and that the "for AI agents" framing is marketing. The author's stated aim is getting "95% stuff right easily".

### 2.2 Neuron today

| Claim | Tag |
| --- | --- |
| The web app has no chart library | VERIFIED (`web/package.json`) |
| The stream has seven event types (`run_started`, `token`, `tool_call`, `final`, `approval_required`, `error`, `done`); none carries structured result data | VERIFIED (`src/neuron_agent/services/streaming.py`) |
| Markdown never loads images, so backend-rendered images would not display today | VERIFIED (`web/src/features/chat/Markdown.tsx`) |
| The content security policy is `default-src 'self'` with no `unsafe-eval` | VERIFIED (`web/nginx.conf`) |
| Citations are validated in code, not trusted from the model | VERIFIED (`src/neuron_agent/schemas/agent.py`) |
| MCP is Streamable HTTP only, results are text capped at 16,384 bytes | VERIFIED (`tools/mcp/client.py`, `config/settings.py`) |
| "No `eval`/shell-executing tools" is a standing rule | VERIFIED (`CLAUDE.md`) |
| Vega's default expression evaluator needs `unsafe-eval`; its interpreter mode avoids it | INFERRED (background knowledge, not re-read) |

### 2.3 Alternatives

| Option | Finding | Tag |
| --- | --- | --- |
| Vega-Lite directly | Strong grammar. Six expression-related XSS advisories were listed for 2025 (for example CVE-2025-26619, CVE-2025-27793). Passing model-written specs through is the risky path. | VERIFIED through advisory aggregators only |
| Apache ECharts, Plotly, Observable Plot, Chart.js | Permissively licensed and suitable as hand-mapped renderers. | INFERRED (licences from background knowledge; confirm before adoption) |
| Head-to-head 2026 benchmark of model-generated specs across these libraries | None found. | VERIFIED (search gap) |
| Data Formulator | MIT, 17.7k stars, 0.7 stable. It is an application built on Flint, not an embeddable component. Useful as proof that Flint has one real product user, from the same team. | VERIFIED (README) |
| AntV `mcp-server-chart` | Supports Streamable HTTP, but renders through a chart service that must be self-hosted to keep data private. | VERIFIED through directory listings only |
| Model-written chart code in a sandbox | Most flexible; conflicts with the no-`eval` rule and adds a code-execution surface. | VERIFIED (rule), INFERRED (assessment) |

## 3. Options

| Shape | Coupling | Security | Streaming and UX | User editing | Effort | Lock-in | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| (a) Agent calls a chart MCP server | Low in code, high in operations | Rows leave Neuron for another process or host | Returns images or a UI card Neuron cannot display | None | M | Medium | Reject |
| (b) Model emits a Flint spec, browser renders | High: Flint's format becomes Neuron's API | The model retypes data into the spec | Good | Good | S | High | Reject as the contract; fine inside an adapter |
| (c) Backend renders static images | Medium | Needs headless Chrome or Node server-side | Static, no hover, blocked by the Markdown image rule | None | M | Medium | Reject |
| (d) Neutral contract, swappable renderers | Lowest | Server validates a tiny spec; data never passes through the model | Good; chart appears with the final answer | Type and axis switches are trivial | M | Low | **Pick** |
| (e) Backend-native spec passthrough or generated code | High | Worst | Flexible | Poor | S to L | High | Reject |

Why (d) beats (b) even though Flint's spec is small: Neuron's contract is nearly the same shape (chart type plus encodings), so the Flint adapter is a thin mapping. Owning the shape costs little and means a Flint breaking change touches one web folder.

## 4. Security rules

- **No data in specs.** The spec references columns; the browser joins it to the gateway rows. Chart numbers then always equal query numbers.
- **Closed schema.** Chart type is an enum, columns must exist in the named result, titles are capped at 120 characters and passed through `displaySafe`.
- **No backend-native passthrough.** No URLs, links, image marks, expressions or HTML tooltips. Themes come from operator configuration only, never from the model or from data.
- **No policy relaxation.** The renderer must work under today's content security policy, with no `unsafe-eval` and no new network destinations.
- **Size limits.** At most 2,000 points, 12 series and 3 charts per answer. Beyond that, show top-N or fall back to the table.
- **Labels are data.** Category values come from the database and are untrusted; they are drawn as text only. Chart titles are model output and get the same treatment as answer text.
- **PII.** Masked columns cannot be encoded. A chart shows nothing the table does not. Exports are audited, and CSV export prefixes cells starting with `=`, `+`, `-` or `@` to stop spreadsheet formula injection.
- **Pinned charts (later)** store the spec and a query reference, not rows, and re-run under the viewer's identity.

## 5. Ranked use cases

| Rank | Feature | Value | Differentiation | Effort | Needs Flint? |
| --- | --- | --- | --- | --- | --- |
| 1 | Answer card: table, SQL and provenance together | High | High | M | No |
| 2 | Inline chart chosen by rules from column roles | High | Medium | S | No |
| 3 | User switches chart type, axes, or back to table | High | Medium | S | No |
| 4 | Export PNG and CSV | Medium | Low | S | No |
| 5 | Themes and branding | Medium | Medium | S | Helps a lot |
| 6 | Native editable Excel chart export | Medium | High | M | Yes |
| 7 | Model-proposed charts for harder questions | Medium | Medium | M | Helps |
| 8 | Pinned charts | Medium | Low | M, needs persistence and an ADR | No |
| 9 | Dashboards | Low now | Low | L | No |

Rankings are judgement (INFERRED).

## 6. Fit with the Data Gateway

- **The gateway stays chart-agnostic.** Its result envelope gains optional column hints in a minor contract version: `role` (time, dimension, measure), `unit`, `format` and `grain`, filled from metric definitions.
- **Neuron's rules use the hints** to choose the default chart. The Flint adapter maps them to Flint's semantic types (a currency unit to `Price`, a month grain to `YearMonth`), so the model never guesses them.
- **Rows reach the browser as a server-attached field on the `final` event**, taken from the tool output and never from the model. This is the same pattern as citations and needs an amendment to ADR 0005's stream contract.

## 7. Roadmap placement

Phases refer to the companion document.

1. **During the gateway proof:** run the two spikes in section 8. No product code.
2. **End of gateway MVP:** ship the answer card with table, SQL and provenance. No chart library.
3. **With governed metrics:** ship the chart contract, rule-based charts, type switching and PNG/CSV export, using the spike's winning renderer.
4. **On a trigger only:** model-proposed charts, themes, Excel export, pinning.

**Deliberately not built:** dashboards, backend image rendering, a chart MCP server, generated chart code, backend-native spec passthrough, cross-filtering.

**Kill criteria:**

- Charts die with the gateway if it fails its own proof.
- Flint is dropped as a renderer if it needs a content security policy relaxation, if issue #129 is still open at adoption time, or if another breaking release lands without migration notes.

## 8. Spike plan

Thresholds are judgement, not measurements.

### Spike 1: chart quality (2 days)

Take 20 analytics questions with real result sets from the gateway proof. Compare three arms on the same model:

- **Rules:** chart chosen from column roles, hand-mapped to one renderer.
- **Flint:** the model writes a Flint spec, with semantic types supplied from the column hints.
- **Vega-Lite:** the model writes Vega-Lite directly.

The maintainer rates each chart blind as acceptable or not, and records validity and output tokens.

| Outcome | Decision |
| --- | --- |
| Flint renders at least 19 of 20, and beats direct Vega-Lite by 2 or more, or matches it with 40% fewer output tokens | Flint is the first renderer |
| Rules reach 17 of 20 acceptable | Ship rules first; defer model-proposed charts |
| Flint fails the first row | Hand-map the contract to one library instead |

### Spike 2: browser fit and safety (1 day)

Build Flint's React component in a throwaway branch under Neuron's exact content security policy. It passes if all three hold:

- No policy violation.
- A lazy-loaded chunk under about 400 KB gzipped with one backend.
- Ten hostile payloads (script in labels, `javascript:` links, bidirectional text, 100,000 rows) cause no script execution, no network request and no broken layout.

## 9. Handoff brief

### Contract (presentation v1.0)

A new ADR is required, numbered after the gateway drafts in the companion document. It also amends ADR 0005 (stream contract) and ADR 0010 (web application).

```json
{
  "presentation_version": "1.0",
  "query_id": "q_01H...",
  "kind": "chart",
  "chart": {
    "type": "line",
    "x": "month",
    "y": ["net_sales"],
    "series": "region",
    "sort": {"by": "x", "order": "asc"},
    "limit": 50
  },
  "title": "Net sales by month"
}
```

- `kind` is `chart`, `table` or `kpi`.
- `type` is one of `bar`, `grouped_bar`, `stacked_bar`, `line`, `area`, `scatter`, `pie`, `heatmap`.
- Column hint on each result column: `{"name", "type", "role", "unit", "format", "grain", "semantic_ref"}`.
- Web renderer interface: `supports(type)`, `render(element, presentation, result, theme)`, `toPng()`. Renderers are lazy-loaded and chosen by web configuration; `none` shows the table only.

### Acceptance criteria

1. The backend has no chart-library dependency, and a test enforces it.
2. A presentation whose `query_id` or columns do not match a result in the same run is dropped and the table is shown.
3. Unknown fields, unknown chart types and over-limit specs are rejected by schema tests.
4. The `final` event carries results and presentations as additive fields; old clients ignore them.
5. Turning charts off in configuration leaves the answer card working.
6. Swapping the renderer changes no file outside the renderer folder.
7. The hostile-payload set from Spike 2 runs as a permanent test.
8. Every chart has a table alternative and passes the existing accessibility checks.

## 10. Limits of this research

- Flint's site pages are client-rendered and could not be read; the mirrored documents in its repository were read instead.
- The paper's evaluation details came partly through a tool summary of the HTML version; the PDF was not read.
- The alternatives' licences and bundle sizes are from background knowledge.
- Vega advisories were seen through aggregator listings, not the original GitHub advisories.

## Sources

- [microsoft/flint-chart](https://github.com/microsoft/flint-chart): README, [CHANGELOG](https://github.com/microsoft/flint-chart/blob/main/CHANGELOG.md), [MCP README](https://github.com/microsoft/flint-chart/blob/main/packages/flint-mcp/README.md), [theme spec](https://github.com/microsoft/flint-chart/blob/main/docs/theme-spec.md), [API reference](https://github.com/microsoft/flint-chart/blob/main/docs/api-reference.md)
- [Microsoft Research blog: Flint, a visualization language for the AI era](https://www.microsoft.com/en-us/research/blog/flint-a-visualization-language-for-the-ai-era/)
- [Flint paper, arXiv 2607.20775](https://arxiv.org/abs/2607.20775)
- [Hacker News discussion](https://news.ycombinator.com/item?id=48834924)
- [microsoft/data-formulator](https://github.com/microsoft/data-formulator)
- Vega advisories: [CVE-2025-26619](https://advisories.gitlab.com/pkg/npm/vega/CVE-2025-26619/), [CVE-2025-27793](https://www.sentinelone.com/vulnerability-database/cve-2025-27793/), [CVE-2025-65110](https://osv.dev/vulnerability/CVE-2025-65110)
- [AntV mcp-server-chart listing](https://glama.ai/mcp/servers/@antvis/mcp-server-chart)
- [Visualization generation with LLMs: an evaluation](https://www.arxiv.org/pdf/2401.11255); [VegaChat](https://web3.arxiv.org/abs/2601.15385)
