# Score: tri4-d3-v4 (d3)

Model, same in every arm: nvidia/nemotron-3-ultra-550b-a55b, temperature 0.
Rates with Wilson 95% intervals in brackets.

| Measure | Arm T4 |
| --- | --- |
| Execution accuracy, questions (every persona right) | 174/200 = 87.0% [81.6, 91.0] |
| Execution accuracy, question-persona units | 560/600 = 93.3% [91.0, 95.1] |
| Same units, nl2data-ref results_match | 75/600 = 12.5% [10.1, 15.4] |
| Accuracy on answerable units where the engine wrote SQL | 542/568 = 95.4% [93.4, 96.9] |
| Answerable units not answered (refused or asked to clarify) | 32/600 = 5.3% [3.8, 7.4] |
| Wrong answers given without refusing or clarifying (units) | 36/900 = 4.0% [2.9, 5.5] |
| Correct refusals, unanswerable questions | 55/60 = 91.7% [81.9, 96.4] |
| Correct refusals, no-access units | 18/18 = 100.0% [82.4, 100.0] |
| Correct clarifications, ambiguous questions | 27/40 = 67.5% [52.0, 79.9] |
| Ambiguous units answered with one reading | 18 |
| Adversarial questions handled correctly | 30/34 = 88.2% [73.4, 95.3] |
| Adversarial units that followed a planted instruction | 0/34 = 0.0% [0.0, 10.2] |
| Statements the guard rejected (never executed) | 0 |
| Statements that failed in the database | 0 |
| Unparsed replies | 0 |
| p95 latency per engine call (s) | 91.9 |
| Model calls | not observable (internal) |

Unscorable under the guard's 1000-row limit: none.
Tables changed during scoring: none.
