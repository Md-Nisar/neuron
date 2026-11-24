# Score: tri3-d3 (d3)

Model, same in every arm: nvidia/nemotron-3-ultra-550b-a55b, temperature 0.
Rates with Wilson 95% intervals in brackets.

| Measure | Arm T3 |
| --- | --- |
| Execution accuracy, questions (every persona right) | 172/200 = 86.0% [80.5, 90.1] |
| Execution accuracy, question-persona units | 556/600 = 92.7% [90.3, 94.5] |
| Same units, nl2data-ref results_match | 73/600 = 12.2% [9.8, 15.0] |
| Accuracy on answerable units where the engine wrote SQL | 540/566 = 95.4% [93.3, 96.9] |
| Answerable units not answered (refused or asked to clarify) | 34/600 = 5.7% [4.1, 7.8] |
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
| p95 latency per engine call (s) | 91.9 |
| Model calls | not observable (internal) |

Unscorable under the guard's 1000-row limit: none.
Tables changed during scoring: none.

