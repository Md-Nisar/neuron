# Score: cb-d2 (d2)

Model, same in every arm: nvidia/nemotron-3-ultra-550b-a55b, temperature 0.
Rates with Wilson 95% intervals in brackets.

| Measure | Arm BP | Arm C |
| --- | --- | --- |
| Execution accuracy, questions (every persona right) | 270/487 = 55.4% [51.0, 59.8] | 248/487 = 50.9% [46.5, 55.3] |
| Execution accuracy, question-persona units | 270/487 = 55.4% [51.0, 59.8] | 248/487 = 50.9% [46.5, 55.3] |
| Same units, nl2data-ref results_match | 141/487 = 28.9% [25.1, 33.1] | 140/487 = 28.7% [24.9, 32.9] |
| Accuracy on answerable units where the engine wrote SQL | 270/454 = 59.5% [54.9, 63.9] | 248/417 = 59.5% [54.7, 64.1] |
| Answerable units not answered (refused or asked to clarify) | 28/487 = 5.8% [4.0, 8.2] | 64/487 = 13.1% [10.4, 16.4] |
| Wrong answers given without refusing or clarifying (units) | 171/487 = 35.1% [31.0, 39.5] | 157/487 = 32.2% [28.2, 36.5] |
| Correct refusals, unanswerable questions | n/a | n/a |
| Correct refusals, no-access units | n/a | n/a |
| Correct clarifications, ambiguous questions | n/a | n/a |
| Ambiguous units answered with one reading | 0 | 0 |
| Adversarial questions handled correctly | n/a | n/a |
| Adversarial units that followed a planted instruction | n/a | n/a |
| Statements the guard rejected (never executed) | 9 | 8 |
| Statements that failed in the database | 4 | 4 |
| Unparsed replies | 5 | 7 |
| p95 latency per engine call (s) | 43.73 | 39.6 |
| Model calls | 500 | 516 |

Unscorable under the guard's 1000-row limit: B-151, B-167, B-299, B-347, B-351, B-364, B-367, B-396, B-440, B-443, B-444, B-447, B-490.
Tables changed during scoring: none.
