# Score: ao-d3-a1 (d3)

Model, same in every arm: nvidia/nemotron-3-ultra-550b-a55b, temperature 0.
Rates with Wilson 95% intervals in brackets.

| Measure | Arm A1 |
| --- | --- |
| Execution accuracy, questions (every persona right) | 158/200 = 79.0% [72.8, 84.1] |
| Execution accuracy, question-persona units | 519/600 = 86.5% [83.5, 89.0] |
| Same units, nl2data-ref results_match | 66/600 = 11.0% [8.7, 13.8] |
| Accuracy on answerable units where the engine wrote SQL | 504/577 = 87.4% [84.4, 89.8] |
| Answerable units not answered (refused or asked to clarify) | 23/600 = 3.8% [2.6, 5.7] |
| Wrong answers given without refusing or clarifying (units) | 224/900 = 24.9% [22.2, 27.8] |
| Correct refusals, unanswerable questions | 30/60 = 50.0% [37.7, 62.3] |
| Correct refusals, no-access units | 15/16 = 93.8% [71.7, 98.9] |
| Correct clarifications, ambiguous questions | 0/40 = 0.0% [0.0, 8.8] |
| Ambiguous units answered with one reading | 39 |
| Adversarial questions handled correctly | 21/34 = 61.8% [45.0, 76.1] |
| Adversarial units that followed a planted instruction | 0/34 = 0.0% [0.0, 10.2] |
| Statements the guard rejected (never executed) | 4 |
| Statements that failed in the database | 0 |
| Unparsed replies | 0 |
| p95 latency per engine call (s) | 79.27 |
| Model calls | not observable (internal) |

Unscorable under the guard's 1000-row limit: none.
Tables changed during scoring: none.
