# Score: full-d3 (d3)

Model, same in every arm: nvidia/nemotron-3-ultra-550b-a55b, temperature 0.
Rates with Wilson 95% intervals in brackets.

| Measure | Arm B | Arm C |
| --- | --- | --- |
| Execution accuracy, questions (every persona right) | 96/200 = 48.0% [41.2, 54.9] | 146/200 = 73.0% [66.5, 78.7] |
| Execution accuracy, question-persona units | 405/600 = 67.5% [63.6, 71.1] | 472/600 = 78.7% [75.2, 81.8] |
| Same units, nl2data-ref results_match | 52/600 = 8.7% [6.7, 11.2] | 75/600 = 12.5% [10.1, 15.4] |
| Accuracy on answerable units where the engine wrote SQL | 389/566 = 68.7% [64.8, 72.4] | 456/555 = 82.2% [78.8, 85.1] |
| Answerable units not answered (refused or asked to clarify) | 34/600 = 5.7% [4.1, 7.8] | 41/600 = 6.8% [5.1, 9.1] |
| Wrong answers given without refusing or clarifying (units) | 24/900 = 2.7% [1.8, 3.9] | 159/900 = 17.7% [15.3, 20.3] |
| Correct refusals, unanswerable questions | 48/60 = 80.0% [68.2, 88.2] | 39/60 = 65.0% [52.4, 75.8] |
| Correct refusals, no-access units | 16/16 = 100.0% [80.6, 100.0] | 16/16 = 100.0% [80.6, 100.0] |
| Correct clarifications, ambiguous questions | 30/40 = 75.0% [59.8, 85.8] | 24/40 = 60.0% [44.6, 73.7] |
| Ambiguous units answered with one reading | 14 | 18 |
| Adversarial questions handled correctly | 22/34 = 64.7% [47.9, 78.5] | 29/34 = 85.3% [69.9, 93.5] |
| Adversarial units that followed a planted instruction | 0/34 = 0.0% [0.0, 10.2] | 0/34 = 0.0% [0.0, 10.2] |
| Statements the guard rejected (never executed) | 181 | 7 |
| Statements that failed in the database | 0 | 0 |
| Unparsed replies | 0 | 6 |
| p95 latency per engine call (s) | 31.25 | 33.73 |
| Model calls | 935 | 934 |

Unscorable under the guard's 1000-row limit: none.
Tables changed during scoring: none.
