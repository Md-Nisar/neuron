# Score: bp-d3 (d3)

Model, same in every arm: nvidia/nemotron-3-ultra-550b-a55b, temperature 0.
Rates with Wilson 95% intervals in brackets.

| Measure | Arm BP |
| --- | --- |
| Execution accuracy, questions (every persona right) | 142/200 = 71.0% [64.4, 76.8] |
| Execution accuracy, question-persona units | 504/600 = 84.0% [80.8, 86.7] |
| Same units, nl2data-ref results_match | 62/600 = 10.3% [8.1, 13.0] |
| Accuracy on answerable units where the engine wrote SQL | 488/577 = 84.6% [81.4, 87.3] |
| Answerable units not answered (refused or asked to clarify) | 23/600 = 3.8% [2.6, 5.7] |
| Wrong answers given without refusing or clarifying (units) | 33/900 = 3.7% [2.6, 5.1] |
| Correct refusals, unanswerable questions | 48/60 = 80.0% [68.2, 88.2] |
| Correct refusals, no-access units | 16/16 = 100.0% [80.6, 100.0] |
| Correct clarifications, ambiguous questions | 27/40 = 67.5% [52.0, 79.9] |
| Ambiguous units answered with one reading | 17 |
| Adversarial questions handled correctly | 29/34 = 85.3% [69.9, 93.5] |
| Adversarial units that followed a planted instruction | 0/34 = 0.0% [0.0, 10.2] |
| Statements the guard rejected (never executed) | 91 |
| Statements that failed in the database | 1 |
| Unparsed replies | 0 |
| p95 latency per engine call (s) | 24.84 |
| Model calls | 951 |

Unscorable under the guard's 1000-row limit: none.
Tables changed during scoring: none.
