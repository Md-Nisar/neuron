# Score: t4l-d3s-v4 (d3)

Model, same in every arm: nvidia/nemotron-3-ultra-550b-a55b, temperature 0.
Rates with Wilson 95% intervals in brackets.

| Measure | Arm T4L |
| --- | --- |
| Execution accuracy, questions (every persona right) | 25/30 = 83.3% [66.4, 92.7] |
| Execution accuracy, question-persona units | 83/90 = 92.2% [84.8, 96.2] |
| Same units, nl2data-ref results_match | 16/90 = 17.8% [11.2, 26.9] |
| Accuracy on answerable units where the engine wrote SQL | 79/82 = 96.3% [89.8, 98.8] |
| Answerable units not answered (refused or asked to clarify) | 8/90 = 8.9% [4.6, 16.6] |
| Wrong answers given without refusing or clarifying (units) | 7/165 = 4.2% [2.1, 8.5] |
| Correct refusals, unanswerable questions | 13/15 = 86.7% [62.1, 96.3] |
| Correct refusals, no-access units | 4/4 = 100.0% [51.0, 100.0] |
| Correct clarifications, ambiguous questions | 6/10 = 60.0% [31.3, 83.2] |
| Ambiguous units answered with one reading | 5 |
| Adversarial questions handled correctly | 30/34 = 88.2% [73.4, 95.3] |
| Adversarial units that followed a planted instruction | 0/34 = 0.0% [0.0, 10.2] |
| Statements the guard rejected (never executed) | 0 |
| Statements that failed in the database | 0 |
| Unparsed replies | 0 |
| p95 latency per engine call (s) | 351.7 |
| Model calls | not observable (internal) |

Unscorable under the guard's 1000-row limit: none.
Tables changed during scoring: none.
