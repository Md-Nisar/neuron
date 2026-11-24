# Score: bp-d1 (d1)

Model, same in every arm: nvidia/nemotron-3-ultra-550b-a55b, temperature 0.
Rates with Wilson 95% intervals in brackets.

| Measure | Arm BP |
| --- | --- |
| Execution accuracy, questions (every persona right) | 9/34 = 26.5% [14.6, 43.1] |
| Execution accuracy, question-persona units | 9/34 = 26.5% [14.6, 43.1] |
| Same units, nl2data-ref results_match | 2/34 = 5.9% [1.6, 19.1] |
| Accuracy on answerable units where the engine wrote SQL | 9/18 = 50.0% [29.0, 71.0] |
| Answerable units not answered (refused or asked to clarify) | 16/34 = 47.1% [31.4, 63.3] |
| Wrong answers given without refusing or clarifying (units) | 8/34 = 23.5% [12.4, 40.0] |
| Correct refusals, unanswerable questions | n/a |
| Correct refusals, no-access units | n/a |
| Correct clarifications, ambiguous questions | n/a |
| Ambiguous units answered with one reading | 0 |
| Adversarial questions handled correctly | n/a |
| Adversarial units that followed a planted instruction | n/a |
| Statements the guard rejected (never executed) | 1 |
| Statements that failed in the database | 0 |
| Unparsed replies | 0 |
| p95 latency per engine call (s) | 26.2 |
| Model calls | 39 |

Unscorable under the guard's 1000-row limit: W-A-012, W-A-033, W-A-035, W-A-039, W-A-040.
Tables changed during scoring: none.
