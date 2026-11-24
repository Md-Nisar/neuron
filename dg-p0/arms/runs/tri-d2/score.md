# Score: tri-d2 (d2)

Model, same in every arm: nvidia/nemotron-3-ultra-550b-a55b, temperature 0.
Rates with Wilson 95% intervals in brackets.

| Measure | Arm T |
| --- | --- |
| Execution accuracy, questions (every persona right) | 285/487 = 58.5% [54.1, 62.8] |
| Execution accuracy, question-persona units | 285/487 = 58.5% [54.1, 62.8] |
| Same units, nl2data-ref results_match | 119/487 = 24.4% [20.8, 28.4] |
| Accuracy on answerable units where the engine wrote SQL | 285/453 = 62.9% [58.4, 67.2] |
| Answerable units not answered (refused or asked to clarify) | 29/487 = 5.9% [4.2, 8.4] |
| Wrong answers given without refusing or clarifying (units) | 162/487 = 33.3% [29.2, 37.6] |
| Correct refusals, unanswerable questions | n/a |
| Correct refusals, no-access units | n/a |
| Correct clarifications, ambiguous questions | n/a |
| Ambiguous units answered with one reading | 0 |
| Adversarial questions handled correctly | n/a |
| Adversarial units that followed a planted instruction | n/a |
| Statements the guard rejected (never executed) | 6 |
| Statements that failed in the database | 0 |
| Unparsed replies | 5 |
| p95 latency per engine call (s) | 81.14 |
| Model calls | not observable (internal) |

Unscorable under the guard's 1000-row limit: B-151, B-167, B-299, B-347, B-351, B-364, B-367, B-396, B-440, B-443, B-444, B-447, B-490.
Tables changed during scoring: none.
