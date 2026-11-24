# Score: ao-d2-a1 (d2)

Model, same in every arm: nvidia/nemotron-3-ultra-550b-a55b, temperature 0.
Rates with Wilson 95% intervals in brackets.

| Measure | Arm A1 |
| --- | --- |
| Execution accuracy, questions (every persona right) | 301/487 = 61.8% [57.4, 66.0] |
| Execution accuracy, question-persona units | 301/487 = 61.8% [57.4, 66.0] |
| Same units, nl2data-ref results_match | 124/487 = 25.5% [21.8, 29.5] |
| Accuracy on answerable units where the engine wrote SQL | 301/485 = 62.1% [57.7, 66.3] |
| Answerable units not answered (refused or asked to clarify) | 2/487 = 0.4% [0.1, 1.5] |
| Wrong answers given without refusing or clarifying (units) | 176/487 = 36.1% [32.0, 40.5] |
| Correct refusals, unanswerable questions | n/a |
| Correct refusals, no-access units | n/a |
| Correct clarifications, ambiguous questions | n/a |
| Ambiguous units answered with one reading | 0 |
| Adversarial questions handled correctly | n/a |
| Adversarial units that followed a planted instruction | n/a |
| Statements the guard rejected (never executed) | 8 |
| Statements that failed in the database | 0 |
| Unparsed replies | 0 |
| p95 latency per engine call (s) | 55.41 |
| Model calls | not observable (internal) |

Unscorable under the guard's 1000-row limit: B-151, B-167, B-299, B-347, B-351, B-364, B-367, B-396, B-440, B-443, B-444, B-447, B-490.
Tables changed during scoring: none.
