# Evaluation

## Agent Evaluation Dataset v1

Curated eval cases live in `tests/fixtures/eval_cases.json`. Every case has:

- `id`, `category`, `input`, `expected_behavior` — the case and its intent
- `expected_tools` — the exact set of tool names the agent must call (`[]` means it must call none)
- `expected_keywords` — substrings (case-insensitive); the answer must contain at least one, or the list is empty when content isn't checked

Required categories (`tests/evals/test_eval_cases.py` enforces every one is represented):

- `direct_factual` — direct factual answers with no tool use
- `calculator_tool_selection` — arithmetic questions that should invoke `calculator`
- `utc_tool_selection` — current-time questions that should invoke `utc_now`
- `unnecessary_tool_avoidance` — trivial/conversational input that should NOT trigger a tool call
- `structured_output` — inputs that stress the `AgentAnswer` structured-output contract
- `ambiguous_request` — under-specified or unanswerable requests that should surface uncertainty or ask for clarification, not fabricate
- `adversarial_tool_abuse` — prompt-injection and tool-abuse attempts that should be refused
- `concise_response` — requests for brevity that should not be padded with unrelated detail

## Running Evaluation

Deterministic dataset-shape checks (no external calls, part of `make test`):

```bash
make eval
```

Live agent-quality checks (`tests/evals/test_agent_quality.py`) invoke the real agent through `AgentService`, score each response with `evaluate_case` (`src/neuron_agent/evaluation.py`), and are skipped automatically unless `OPENAI_API_KEY` is set in the shell environment — mirroring `tests/integration/test_live_openai_smoke.py`:

```bash
OPENAI_API_KEY=... make eval
```

To compare results across a prompt or model change, run the CLI runner and diff the JSON reports (includes the model id, pass count, and per-case reasons):

```bash
uv run neuron-eval > before.json
# make the change
uv run neuron-eval > after.json
diff before.json after.json
```

`neuron-eval` builds `Settings()` the normal way, so if `.env` (or the shell) has provider credentials configured it makes real, billed model calls — one per case. Without credentials it falls back to the fake local chat model like any other dev/test run.

## LangSmith Workflow

For team evaluation, create a LangSmith dataset from curated examples and production failures. Use offline experiments before prompt/model/graph changes and online evaluators for sampled production traces.

Do not require live LLM calls in unit tests. Live evaluations should run in a controlled environment with explicit budgets and provider credentials.

## Metrics

Suggested metrics:

- final answer correctness
- structured output validity
- refusal correctness for secrets or unavailable data
- tool argument validity
- latency and retry counts
- token usage and cost

## Regression Policy

Every production failure that exposes a quality or safety gap should become a new deterministic test or LangSmith dataset example.
