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

## Agent Evaluation Dataset v2: Multi-Turn (v0.3.0)

Multi-turn cases live in `tests/fixtures/eval_multi_turn_cases.json`. Each case has the v1 fields plus `setup`, a non-empty list of earlier user turns.

`run_multi_turn_suite` (`src/neuron_agent/evaluation.py`) plays each case on **one new thread**: the `setup` turns in order, then `input`. Only the final turn is scored, with the same pass criteria as v1:
- non-empty answer;
- confidence in [0, 1];
- the tools used for that turn match `expected_tools` exactly;
- at least one `expected_keywords` entry appears (case-insensitive).

It needs thread persistence: `APP_CHECKPOINTER` resolving to `memory` (the default in development and test) or `postgres`. It refuses to run with `none`.

Required categories (`tests/evals/test_eval_cases.py` enforces every one, and at least 10 cases):

- `reference_resolution`: the final turn refers back with "the second one", "them", "the deadline".
- `context_carryover`: recall a detail or honour an instruction from an earlier turn.
- `tool_use_across_turns`: the operands come from earlier turns, and the calculator is still selected.
- `correction_handling`: a later correction wins over the earlier statement.
- `long_thread`: an early fact is recalled, or a tool is used correctly, after more than 10 turns, within the default `APP_MAX_HISTORY_TOKENS`.
- `injection_persistence`: an instruction planted in an earlier turn must not unlock tool calls (`expected_tools: []`).

`tests/evals/test_multi_turn_harness.py` checks the harness deterministically, with no model: every case's final model input carries all of its turns in order, single-turn cases never share a thread, and the CLI report is clean JSON.

## Running Evaluation

Deterministic dataset-shape checks (no external calls, part of `make test`):

```bash
make eval
```

Live agent-quality checks (`tests/evals/test_agent_quality.py`) invoke the real agent through `AgentService`, score each response with `evaluate_case` (`src/neuron_agent/evaluation.py`), and are skipped automatically unless `OPENAI_API_KEY` is set in the shell environment — mirroring `tests/integration/test_live_openai_smoke.py`:

```bash
OPENAI_API_KEY=... make eval
```

Live checks cover both datasets: `test_agent_passes_every_eval_case` and `test_agent_passes_every_multi_turn_eval_case`.

To compare results across a prompt or model change, run the CLI runner and diff the JSON reports. Each report includes the model ID, the pass count and per-case reasons, with the multi-turn results under `multi_turn`. stdout carries only the JSON report; run logs go to stderr.

```bash
uv run neuron-eval > before.json
# make the change
uv run neuron-eval > after.json
diff before.json after.json
```

`neuron-eval` builds `Settings()` the normal way, so if `.env` (or the shell) has provider credentials configured it makes real, billed model calls: one per single-turn case, and one per turn (`setup` plus `input`) for multi-turn cases, 46 for dataset v2. Without credentials it falls back to the fake local chat model like any other dev/test run.

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
