# Score: t4l-fresh-d28 (d3)

Model, same in every arm: nvidia/nemotron-3-ultra-550b-a55b, temperature 0.
Rates with Wilson 95% intervals in brackets.

| Measure | Arm T4L |
| --- | --- |
| Execution accuracy, questions (every persona right) | 32/40 = 80.0% [65.2, 89.5] |
| Execution accuracy, question-persona units | 108/120 = 90.0% [83.3, 94.2] |
| Same units, nl2data-ref results_match | 19/120 = 15.8% [10.4, 23.4] |
| Accuracy on answerable units where the engine wrote SQL | 94/96 = 97.9% [92.7, 99.4] |
| Answerable units not answered (refused or asked to clarify) | 23/120 = 19.2% [13.1, 27.1] |
| Wrong answers given without refusing or clarifying (units) | 1/240 = 0.4% [0.1, 2.3] |
| Correct refusals, unanswerable questions | 36/40 = 90.0% [77.0, 96.0] |
| Correct refusals, no-access units | 14/16 = 87.5% [64.0, 96.5] |
| Correct clarifications, ambiguous questions | n/a |
| Ambiguous units answered with one reading | 0 |
| Adversarial questions handled correctly | n/a |
| Adversarial units that followed a planted instruction | n/a |
| Statements the guard rejected (never executed) | 0 |
| Statements that failed in the database | 0 |
| Unparsed replies | 1 |
| p95 latency per engine call (s) | 221.51 |
| Model calls | 678 |

Unscorable under the guard's 1000-row limit: none.
Tables changed during scoring: none.
