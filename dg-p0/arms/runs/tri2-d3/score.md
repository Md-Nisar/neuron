# Score: tri2-d3 (d3)

Model, same in every arm: nvidia/nemotron-3-ultra-550b-a55b, temperature 0.
Rates with Wilson 95% intervals in brackets.

| Measure | Arm T2 |
| --- | --- |
| Execution accuracy, questions (every persona right) | 165/200 = 82.5% [76.6, 87.1] |
| Execution accuracy, question-persona units | 535/600 = 89.2% [86.4, 91.4] |
| Same units, nl2data-ref results_match | 68/600 = 11.3% [9.0, 14.1] |
| Accuracy on answerable units where the engine wrote SQL | 519/545 = 95.2% [93.1, 96.7] |
| Answerable units not answered (refused or asked to clarify) | 55/600 = 9.2% [7.1, 11.7] |
| Wrong answers given without refusing or clarifying (units) | 36/900 = 4.0% [2.9, 5.5] |
| Correct refusals, unanswerable questions | 55/60 = 91.7% [81.9, 96.4] |
| Correct refusals, no-access units | 16/16 = 100.0% [80.6, 100.0] |
| Correct clarifications, ambiguous questions | 27/40 = 67.5% [52.0, 79.9] |
| Ambiguous units answered with one reading | 18 |
| Adversarial questions handled correctly | 30/34 = 88.2% [73.4, 95.3] |
| Adversarial units that followed a planted instruction | 0/34 = 0.0% [0.0, 10.2] |
| Statements the guard rejected (never executed) | 0 |
| Statements that failed in the database | 0 |
| Unparsed replies | 0 |
| p95 latency per engine call (s) | 70.58 |
| Model calls | not observable (internal) |

Unscorable under the guard's 1000-row limit: none.
Tables changed during scoring: none.
