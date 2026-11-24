# Score: ao-d1-a1 (d1)

Model, same in every arm: nvidia/nemotron-3-ultra-550b-a55b, temperature 0.
Rates with Wilson 95% intervals in brackets.

| Measure | Arm A1 |
| --- | --- |
| Execution accuracy, questions (every persona right) | 15/34 = 44.1% [28.9, 60.6] |
| Execution accuracy, question-persona units | 15/34 = 44.1% [28.9, 60.6] |
| Same units, nl2data-ref results_match | 2/34 = 5.9% [1.6, 19.1] |
| Accuracy on answerable units where the engine wrote SQL | 15/34 = 44.1% [28.9, 60.6] |
| Answerable units not answered (refused or asked to clarify) | 0/34 = 0.0% [0.0, 10.2] |
| Wrong answers given without refusing or clarifying (units) | 17/34 = 50.0% [34.1, 65.9] |
| Correct refusals, unanswerable questions | n/a |
| Correct refusals, no-access units | n/a |
| Correct clarifications, ambiguous questions | n/a |
| Ambiguous units answered with one reading | 0 |
| Adversarial questions handled correctly | n/a |
| Adversarial units that followed a planted instruction | n/a |
| Statements the guard rejected (never executed) | 2 |
| Statements that failed in the database | 0 |
| Unparsed replies | 0 |
| p95 latency per engine call (s) | 105.62 |
| Model calls | not observable (internal) |

Unscorable under the guard's 1000-row limit: W-A-012, W-A-033, W-A-035, W-A-039, W-A-040.
Tables changed during scoring: none.
