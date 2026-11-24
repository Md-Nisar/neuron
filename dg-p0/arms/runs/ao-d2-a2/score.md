# Score: ao-d2-a2 (d2)

Model, same in every arm: nvidia/nemotron-3-ultra-550b-a55b, temperature 0.
Rates with Wilson 95% intervals in brackets.

| Measure | Arm A2 |
| --- | --- |
| Execution accuracy, questions (every persona right) | 293/487 = 60.2% [55.8, 64.4] |
| Execution accuracy, question-persona units | 293/487 = 60.2% [55.8, 64.4] |
| Same units, nl2data-ref results_match | 121/487 = 24.9% [21.2, 28.9] |
| Accuracy on answerable units where the engine wrote SQL | 293/486 = 60.3% [55.9, 64.5] |
| Answerable units not answered (refused or asked to clarify) | 1/487 = 0.2% [0.0, 1.1] |
| Wrong answers given without refusing or clarifying (units) | 186/487 = 38.2% [34.0, 42.6] |
| Correct refusals, unanswerable questions | n/a |
| Correct refusals, no-access units | n/a |
| Correct clarifications, ambiguous questions | n/a |
| Ambiguous units answered with one reading | 0 |
| Adversarial questions handled correctly | n/a |
| Adversarial units that followed a planted instruction | n/a |
| Statements the guard rejected (never executed) | 7 |
| Statements that failed in the database | 0 |
| Unparsed replies | 0 |
| p95 latency per engine call (s) | 62.24 |
| Model calls | not observable (internal) |

Unscorable under the guard's 1000-row limit: B-151, B-167, B-299, B-347, B-351, B-364, B-367, B-396, B-440, B-443, B-444, B-447, B-490.
Tables changed during scoring: none.
