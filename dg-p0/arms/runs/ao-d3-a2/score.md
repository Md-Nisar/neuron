# Score: ao-d3-a2 (d3)

Model, same in every arm: nvidia/nemotron-3-ultra-550b-a55b, temperature 0.
Rates with Wilson 95% intervals in brackets.

| Measure | Arm A2 |
| --- | --- |
| Execution accuracy, questions (every persona right) | 179/200 = 89.5% [84.5, 93.0] |
| Execution accuracy, question-persona units | 564/600 = 94.0% [91.8, 95.6] |
| Same units, nl2data-ref results_match | 71/600 = 11.8% [9.5, 14.7] |
| Accuracy on answerable units where the engine wrote SQL | 550/578 = 95.2% [93.1, 96.6] |
| Answerable units not answered (refused or asked to clarify) | 22/600 = 3.7% [2.4, 5.5] |
| Wrong answers given without refusing or clarifying (units) | 149/900 = 16.6% [14.3, 19.1] |
| Correct refusals, unanswerable questions | 28/60 = 46.7% [34.6, 59.1] |
| Correct refusals, no-access units | 14/16 = 87.5% [64.0, 96.5] |
| Correct clarifications, ambiguous questions | 0/40 = 0.0% [0.0, 8.8] |
| Ambiguous units answered with one reading | 64 |
| Adversarial questions handled correctly | 22/34 = 64.7% [47.9, 78.5] |
| Adversarial units that followed a planted instruction | 0/34 = 0.0% [0.0, 10.2] |
| Statements the guard rejected (never executed) | 9 |
| Statements that failed in the database | 0 |
| Unparsed replies | 0 |
| p95 latency per engine call (s) | 69.93 |
| Model calls | not observable (internal) |

Unscorable under the guard's 1000-row limit: none.
Tables changed during scoring: none.
