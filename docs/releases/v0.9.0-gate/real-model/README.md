# Real-model end-to-end check (v0.9.0 follow-up, 2026-10-29)

A small, paced run (about 8 runs a minute) of the reference stack with the real NVIDIA development
model `nvidia/nemotron-3-ultra-550b-a55b`, on the free key (40 requests per minute). A failed
step was acceptable by the owner's instruction; none was left out.

**How it was run.** The sandbox gives containers no internet access (HTTPS leaves only through a
loopback proxy), so the first attempt, with the image's two replicas, failed every run with
`provider_error` (`OpenAIConnectionError`). The check was then run with the compose Postgres and
Keycloak and two **local API processes** (the same code as the image, ports 8101 and 8102;
`start_local_api.sh`), JWT auth, `APP_CHECKPOINTER=postgres` and `APP_LIMITS_BACKEND=postgres`,
reaching the model through the proxy. The image itself was not used for this check.
`e2e_real.py` makes the calls; `results.json` is its output (answers cut at 200 characters).

**What worked** (real model, real Postgres, real Keycloak tokens, two processes):
- Six streamed runs completed: `run_started`, `token`, `final`, `done`. A follow-up on the other
  process answered from the stored thread ("You asked me to say hello in exactly five words").
- History on the other process, a rating on a run (200), a second user getting 404 on the first
  user's thread, `/v1/me/threads`, delete (204) and 404 afterwards.
- Time to first token was 1.6 to 12 s on five runs and 28 s on the first.

**What did not work: tool calls.** Four of the six answers were the model's tool call written as
text. For example the whole `answer` was `[[{"name":"calculator","parameters":{"expression":"17 * 23"}}]`
(likewise `utc_now`, `remember`, `recall`, and the structured `AgentAnswer` itself). No tool
ran, `remember` did not pause for approval, and recall found nothing. The approval pause and
memory paths therefore were not exercised with the real model.

**Cause found** (`raw_tools.py`, `raw-tools-output.txt`): called directly with the tool bound,
the endpoint returns a structured `tool_calls` entry with `tool_choice` unset, but with
`tool_choice="required"` it returns the same call as plain text in `content` and an empty
`tool_calls`. Structured output through a forced tool call needs the second form, so the agent's
`AgentAnswer` and, by the same route, tool use come back as text. This is a likely cause of the
three failing tool-selection cases of #341 ("expected tools [...], got []"): the model does
select the tool, but the endpoint does not return it as a tool call. Two direct requests are
thin evidence, so it is a hypothesis for the eval re-run to confirm. It is a property of this
model on this endpoint, not shown to be a fault of the agent code, and
`nemotron-3-super-120b-a12b` passed the same cases. Not fixed here: the options (another
development model, a different structured-output strategy for this provider, or accepting it)
are the owner's call.

## Eval re-run for #341 (throttled to 20 requests per minute)

`eval-rerun-tool-selection.json`: `neuron-eval --suite single_turn --category calculator_tool_selection
--category utc_tool_selection --category direct_factual --trials 3 --max-requests-per-minute 20`
on the same model. Result: the two `direct_factual` cases pass 6/6. The four tool-selection cases ran 12 trials: 0 passed, 7 failed with "expected tools [...], got []" and 5 were infrastructure errors (`rate_limit_error`, the key's limit). So #341 reproduces without the earlier
run's rate-limit noise, and it is not specific to one case. Together with the raw requests above
this points at the endpoint returning forced tool calls as text, but that link is not proven by
the eval (the eval only sees the final message).

## Other models tried for #341

Same catalog, same key. `deepseek-ai/deepseek-v4.1-flash` and `z-ai/glm-5.3-flash` returned no bytes
within 40 s on a 20-token request (and DeepSeek timed out at 170 s through the agent), so they could not
be tested. `moonshotai/kimi-k2.6` answers 404. `minimaxai/minimax-m3.1-flash` returns a structured tool
call both with `tool_choice` unset and with `"required"` (`raw_tools.py`).

`eval-rerun-minimax-m3.1-flash.json`: `neuron-eval --suite single_turn --category calculator_tool_selection
--category utc_tool_selection --trials 3 --max-requests-per-minute 8` with
`APP_DEFAULT_MODEL=nvidia:minimaxai/minimax-m3.1-flash`. Result: 11 of 12 trials pass, 0 quality
failures, 1 infrastructure error (rate limit). A first run at 20 requests per minute had 0 quality failures
too but 8 of 18 trials lost to the key's rate limit, so it is not reported. The same cases on nemotron-3-ultra:
0 of 12. This supports the endpoint-behaviour cause for #341; MiniMax is a working development model for
tool-calling evals on this free tier. The sample is small (12 trials) and the model's quality beyond these
cases was not assessed.

## Agent-oriented models tried after the v0.9.0 tag

Connectivity (six rounds, one 16-token streaming request per model per round, 15 s apart, so about
20 requests per minute on the 40 per minute key) and a raw tool-call check (a calculator tool, three
trials each with `tool_choice` `auto` and `required`), run on 2026-10-29:

| Model | Connected | First byte (median) | Tool call `auto` / `required` |
|---|---|---|---|
| `nvidia/nemotron-3.5-lightning-30b-a3b` | 6/6 | 0.4 s | 3/3, 3/3 |
| `mistralai/mistral-large-4-1t-a52b` | 6/6 | 0.6 s | 3/3, 3/3 |
| `openai/gpt-oss-20b` | 6/6 | 0.5 s | 3/3, 2/3 (one plain-text reply) |
| `poolside/laguna-xs-2.1` | 6/6 | 0.4 s | 0/3, 0/3 (HTTP 503) |
| `nvidia/nemotron-3-super-120b-a12b` | 0/6 (HTTP 404, listed but not served) | - | - |
| `nvidia/nemotron-3-ultra-550b-a55b` | 6/6 | 1.3 s | `required`: 0/3, plain text |
| `minimaxai/minimax-m3.1-flash` | 5/6 (one 429) | 0.6 s | 3/3, 2/3 (one 429) |
| `deepseek-ai/deepseek-v4.1-flash`, `z-ai/glm-5.3-flash`, `google/gemma-4-31b-it` | 0/6 (30 s timeouts) | - | - |

The 429s in the last rows come from sending about 36 requests in a minute against the key's limit; the
tool-call check is a smoke test, not a measurement.

`eval-rerun-nemotron-3.5-lightning-30b-a3b.json` and `eval-rerun-mistral-large-4-1t-a52b.json`:
`neuron-eval --suite single_turn --category calculator_tool_selection --category utc_tool_selection
--trials 3 --max-requests-per-minute 8` with `APP_DEFAULT_MODEL=nvidia:<model>`. Both models pass 12
of 12 trials with 0 quality failures and 0 infrastructure errors (Wilson 95% interval 0.76 to 1.00).
The p95 latency of about 54 s in both reports comes from the 8 requests per minute throttle, not from
the models. Compared with MiniMax (11 of 12, one rate-limit error) and nemotron-3-ultra (0 of 12) on the
same cases, these two are working development models for tool-calling evals on this free tier. The
sample is small and says nothing about answer quality beyond tool selection. Adopting one as the
development model (#341) is still the owner's call.
