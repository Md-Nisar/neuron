# Score: t4l-fresh (d3)

Model, same in every arm: nvidia/nemotron-3-ultra-550b-a55b, temperature 0.
Rates with Wilson 95% intervals in brackets.

| Measure | Arm T4L |
| --- | --- |
| Execution accuracy, questions (every persona right) | 24/40 = 60.0% [44.6, 73.7] |
| Execution accuracy, question-persona units | 96/120 = 80.0% [72.0, 86.2] |
| Same units, nl2data-ref results_match | 5/120 = 4.2% [1.8, 9.4] |
| Accuracy on answerable units where the engine wrote SQL | 96/96 = 100.0% [96.2, 100.0] |
| Answerable units not answered (refused or asked to clarify) | 23/120 = 19.2% [13.1, 27.1] |
| Wrong answers given without refusing or clarifying (units) | 1/240 = 0.4% [0.1, 2.3] |
| Correct refusals, unanswerable questions | 36/40 = 90.0% [77.0, 96.0] |
| Correct refusals, no-access units | n/a |
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
