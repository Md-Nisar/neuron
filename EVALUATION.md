# Evaluation

## Local Regression Cases

Deterministic eval fixtures live in `tests/fixtures/eval_cases.json` and are validated by `tests/evals/test_eval_cases.py`.

Current categories:

- tool selection
- prompt injection
- truthfulness/uncertainty

Run:

```bash
make eval
```

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
