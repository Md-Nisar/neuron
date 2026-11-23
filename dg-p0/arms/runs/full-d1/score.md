# Score: full-d1 (d1)

Model, same in every arm: nvidia/nemotron-3-ultra-550b-a55b, temperature 0.
Rates with Wilson 95% intervals in brackets.

| Measure | Arm B | Arm C |
| --- | --- | --- |
| Execution accuracy, questions (every persona right) | 8/34 = 23.5% [12.4, 40.0] | 7/34 = 20.6% [10.3, 36.8] |
| Execution accuracy, question-persona units | 8/34 = 23.5% [12.4, 40.0] | 7/34 = 20.6% [10.3, 36.8] |
| Same units, nl2data-ref results_match | 2/34 = 5.9% [1.6, 19.1] | 2/34 = 5.9% [1.6, 19.1] |
| Accuracy on answerable units where the engine wrote SQL | 8/16 = 50.0% [28.0, 72.0] | 7/16 = 43.8% [23.1, 66.8] |
| Answerable units not answered (refused or asked to clarify) | 18/34 = 52.9% [36.7, 68.5] | 18/34 = 52.9% [36.7, 68.5] |
| Wrong answers given without refusing or clarifying (units) | 7/34 = 20.6% [10.3, 36.8] | 9/34 = 26.5% [14.6, 43.1] |
| Correct refusals, unanswerable questions | n/a | n/a |
| Correct refusals, no-access units | n/a | n/a |
| Correct clarifications, ambiguous questions | n/a | n/a |
| Ambiguous units answered with one reading | 0 | 0 |
| Adversarial questions handled correctly | n/a | n/a |
| Adversarial units that followed a planted instruction | n/a | n/a |
| Statements the guard rejected (never executed) | 1 | 0 |
| Statements that failed in the database | 0 | 0 |
| Unparsed replies | 0 | 0 |
| p95 latency per engine call (s) | 27.36 | 21.03 |
| Model calls | 39 | 39 |

Unscorable under the guard's 1000-row limit: W-A-012, W-A-033, W-A-035, W-A-039, W-A-040.
Tables changed during scoring: none.
