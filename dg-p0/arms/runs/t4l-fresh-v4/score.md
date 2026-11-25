# Score: t4l-fresh-v4 (d3)

Model, same in every arm: nvidia/nemotron-3-ultra-550b-a55b, temperature 0.
Rates with Wilson 95% intervals in brackets.

| Measure | Arm T4L |
| --- | --- |
| Execution accuracy, questions (every persona right) | 33/40 = 82.5% [68.0, 91.2] |
| Execution accuracy, question-persona units | 110/120 = 91.7% [85.3, 95.4] |
| Same units, nl2data-ref results_match | 21/120 = 17.5% [11.7, 25.3] |
| Accuracy on answerable units where the engine wrote SQL | 94/94 = 100.0% [96.1, 100.0] |
| Answerable units not answered (refused or asked to clarify) | 25/120 = 20.8% [14.5, 28.9] |
| Wrong answers given without refusing or clarifying (units) | 1/240 = 0.4% [0.1, 2.3] |
| Correct refusals, unanswerable questions | 36/40 = 90.0% [77.0, 96.0] |
| Correct refusals, no-access units | 16/16 = 100.0% [80.6, 100.0] |
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
