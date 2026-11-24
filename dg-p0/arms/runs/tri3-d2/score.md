# Score: tri3-d2 (d2)

Model, same in every arm: nvidia/nemotron-3-ultra-550b-a55b, temperature 0.
Rates with Wilson 95% intervals in brackets.

| Measure | Arm T3 |
| --- | --- |
| Execution accuracy, questions (every persona right) | 272/487 = 55.9% [51.4, 60.2] |
| Execution accuracy, question-persona units | 272/487 = 55.9% [51.4, 60.2] |
| Same units, nl2data-ref results_match | 114/487 = 23.4% [19.9, 27.4] |
| Accuracy on answerable units where the engine wrote SQL | 272/430 = 63.3% [58.6, 67.7] |
| Answerable units not answered (refused or asked to clarify) | 52/487 = 10.7% [8.2, 13.7] |
| Wrong answers given without refusing or clarifying (units) | 153/487 = 31.4% [27.5, 35.7] |
| Correct refusals, unanswerable questions | n/a |
| Correct refusals, no-access units | n/a |
| Correct clarifications, ambiguous questions | n/a |
| Ambiguous units answered with one reading | 0 |
| Adversarial questions handled correctly | n/a |
| Adversarial units that followed a planted instruction | n/a |
| Statements the guard rejected (never executed) | 5 |
| Statements that failed in the database | 0 |
| Unparsed replies | 5 |
| p95 latency per engine call (s) | 120.39 |
| Model calls | not observable (internal) |

Unscorable under the guard's 1000-row limit: B-151, B-167, B-299, B-347, B-351, B-364, B-367, B-396, B-440, B-443, B-444, B-447, B-490.
Tables changed during scoring: none.

