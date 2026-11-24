# Score: tri-d3 (d3)

Model, same in every arm: nvidia/nemotron-3-ultra-550b-a55b, temperature 0.
Rates with Wilson 95% intervals in brackets.

| Measure | Arm T |
| --- | --- |
| Execution accuracy, questions (every persona right) | 173/200 = 86.5% [81.1, 90.5] |
| Execution accuracy, question-persona units | 559/600 = 93.2% [90.9, 94.9] |
| Same units, nl2data-ref results_match | 73/600 = 12.2% [9.8, 15.0] |
| Accuracy on answerable units where the engine wrote SQL | 543/569 = 95.4% [93.4, 96.9] |
| Answerable units not answered (refused or asked to clarify) | 31/600 = 5.2% [3.7, 7.2] |
| Wrong answers given without refusing or clarifying (units) | 53/900 = 5.9% [4.5, 7.6] |
| Correct refusals, unanswerable questions | 50/60 = 83.3% [72.0, 90.7] |
| Correct refusals, no-access units | 16/16 = 100.0% [80.6, 100.0] |
| Correct clarifications, ambiguous questions | 27/40 = 67.5% [52.0, 79.9] |
| Ambiguous units answered with one reading | 18 |
| Adversarial questions handled correctly | 30/34 = 88.2% [73.4, 95.3] |
| Adversarial units that followed a planted instruction | 0/34 = 0.0% [0.0, 10.2] |
| Statements the guard rejected (never executed) | 0 |
| Statements that failed in the database | 0 |
| Unparsed replies | 0 |
| p95 latency per engine call (s) | 52.1 |
| Model calls | not observable (internal) |

Unscorable under the guard's 1000-row limit: none.
Tables changed during scoring: none.
