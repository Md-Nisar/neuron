# Score: tri4-d2 (d2)

Model, same in every arm: nvidia/nemotron-3-ultra-550b-a55b, temperature 0.
Rates with Wilson 95% intervals in brackets.

| Measure | Arm T4 |
| --- | --- |
| Execution accuracy, questions (every persona right) | 279/487 = 57.3% [52.9, 61.6] |
| Execution accuracy, question-persona units | 279/487 = 57.3% [52.9, 61.6] |
| Same units, nl2data-ref results_match | 117/487 = 24.0% [20.4, 28.0] |
| Accuracy on answerable units where the engine wrote SQL | 279/442 = 63.1% [58.5, 67.5] |
| Answerable units not answered (refused or asked to clarify) | 40/487 = 8.2% [6.1, 11.0] |
| Wrong answers given without refusing or clarifying (units) | 157/487 = 32.2% [28.2, 36.5] |
| Correct refusals, unanswerable questions | n/a |
| Correct refusals, no-access units | n/a |
| Correct clarifications, ambiguous questions | n/a |
| Ambiguous units answered with one reading | 0 |
| Adversarial questions handled correctly | n/a |
| Adversarial units that followed a planted instruction | n/a |
| Statements the guard rejected (never executed) | 6 |
| Statements that failed in the database | 0 |
| Unparsed replies | 5 |
| p95 latency per engine call (s) | 120.39 |
| Model calls | not observable (internal) |

Unscorable under the guard's 1000-row limit: B-151, B-167, B-299, B-347, B-351, B-364, B-367, B-396, B-440, B-443, B-444, B-447, B-490.
Tables changed during scoring: none.

