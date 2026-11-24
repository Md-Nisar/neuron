# DG-00.05 results

Model in every arm: nvidia/nemotron-3-ultra-550b-a55b (`LLM_MODEL`). Rates with Wilson 95% intervals.
Every SQL answer, from every arm, went through the same guard and the persona's read-only executor.

## D3, the Neuron mart (200 answerable, 60 unanswerable, 40 ambiguous, 34 adversarial; 3 personas)

| Measure | C | B (D16) | A1 | A2 | B, model only (DG-00.03) |
| --- | --- | --- | --- | --- | --- |
| Execution accuracy, answerable questions (every persona right) | 146/200 = 73.0% [66.5, 78.7] | 142/200 = 71.0% [64.4, 76.8] | 158/200 = 79.0% [72.8, 84.1] | 179/200 = 89.5% [84.5, 93.0] | 96/200 = 48.0% [41.2, 54.9] |
| Execution accuracy, answerable units | 472/600 = 78.7% [75.2, 81.8] | 504/600 = 84.0% [80.8, 86.7] | 519/600 = 86.5% [83.5, 89.0] | 564/600 = 94.0% [91.8, 95.6] | 405/600 = 67.5% [63.6, 71.1] |
| Accuracy where the engine wrote SQL | 456/555 = 82.2% [78.8, 85.1] | 488/577 = 84.6% [81.4, 87.3] | 504/577 = 87.4% [84.4, 89.8] | 550/578 = 95.2% [93.1, 96.6] | 389/566 = 68.7% [64.8, 72.4] |
| Answerable units not answered (refused or clarified) | 41/600 = 6.8% [5.1, 9.1] | 23/600 = 3.8% [2.6, 5.7] | 23/600 = 3.8% [2.6, 5.7] | 22/600 = 3.7% [2.4, 5.5] | 34/600 = 5.7% [4.1, 7.8] |
| Wrong answers without refusal or clarification (units) | 159/900 = 17.7% [15.3, 20.3] | 33/900 = 3.7% [2.6, 5.1] | 224/900 = 24.9% [22.2, 27.8] | 149/900 = 16.6% [14.3, 19.1] | 24/900 = 2.7% [1.8, 3.9] |
| Correct refusals, unanswerable questions | 39/60 = 65.0% [52.4, 75.8] | 48/60 = 80.0% [68.2, 88.2] | 30/60 = 50.0% [37.7, 62.3] | 28/60 = 46.7% [34.6, 59.1] | 48/60 = 80.0% [68.2, 88.2] |
| Correct refusals, no-access units | 16/16 = 100.0% [80.6, 100.0] | 16/16 = 100.0% [80.6, 100.0] | 15/16 = 93.8% [71.7, 98.9] | 14/16 = 87.5% [64.0, 96.5] | 16/16 = 100.0% [80.6, 100.0] |
| Correct clarifications, ambiguous questions | 24/40 = 60.0% [44.6, 73.7] | 27/40 = 67.5% [52.0, 79.9] | 0/40 = 0.0% [0.0, 8.8] | 0/40 = 0.0% [0.0, 8.8] | 30/40 = 75.0% [59.8, 85.8] |
| Adversarial questions handled correctly | 29/34 = 85.3% [69.9, 93.5] | 29/34 = 85.3% [69.9, 93.5] | 21/34 = 61.8% [45.0, 76.1] | 22/34 = 64.7% [47.9, 78.5] | 22/34 = 64.7% [47.9, 78.5] |
| Adversarial units that followed a planted instruction | 0/34 = 0.0% [0.0, 10.2] | 0/34 = 0.0% [0.0, 10.2] | 0/34 = 0.0% [0.0, 10.2] | 0/34 = 0.0% [0.0, 10.2] | 0/34 = 0.0% [0.0, 10.2] |
| Statements the guard rejected (never executed) | 7 | 91 | 4 | 9 | 181 |
| Statements that failed in the database | 0 | 1 | 0 | 0 | 0 |
| p95 latency per question (s) | 33.73 | 24.84 | 79.27 | 69.93 | 31.25 |
| Model calls | 934 | 951 | not observable | not observable | 935 |
| Units scored | 934 | 934 | 934 | 934 | 934 |

## D1, Wide World Importers (39 questions, one reader)

| Measure | C | B (D16) | A1 | A2 | B, model only (DG-00.03) |
| --- | --- | --- | --- | --- | --- |
| Execution accuracy, answerable questions (every persona right) | 7/34 = 20.6% [10.3, 36.8] | 9/34 = 26.5% [14.6, 43.1] | 15/34 = 44.1% [28.9, 60.6] | 14/34 = 41.2% [26.4, 57.8] | 8/34 = 23.5% [12.4, 40.0] |
| Execution accuracy, answerable units | 7/34 = 20.6% [10.3, 36.8] | 9/34 = 26.5% [14.6, 43.1] | 15/34 = 44.1% [28.9, 60.6] | 14/34 = 41.2% [26.4, 57.8] | 8/34 = 23.5% [12.4, 40.0] |
| Accuracy where the engine wrote SQL | 7/16 = 43.8% [23.1, 66.8] | 9/18 = 50.0% [29.0, 71.0] | 15/34 = 44.1% [28.9, 60.6] | 14/33 = 42.4% [27.2, 59.2] | 8/16 = 50.0% [28.0, 72.0] |
| Answerable units not answered (refused or clarified) | 18/34 = 52.9% [36.7, 68.5] | 16/34 = 47.1% [31.4, 63.3] | 0/34 = 0.0% [0.0, 10.2] | 1/34 = 2.9% [0.5, 14.9] | 18/34 = 52.9% [36.7, 68.5] |
| Wrong answers without refusal or clarification (units) | 9/34 = 26.5% [14.6, 43.1] | 8/34 = 23.5% [12.4, 40.0] | 17/34 = 50.0% [34.1, 65.9] | 18/34 = 52.9% [36.7, 68.5] | 7/34 = 20.6% [10.3, 36.8] |
| Correct refusals, unanswerable questions | n/a | n/a | n/a | n/a | n/a |
| Correct refusals, no-access units | n/a | n/a | n/a | n/a | n/a |
| Correct clarifications, ambiguous questions | n/a | n/a | n/a | n/a | n/a |
| Adversarial questions handled correctly | n/a | n/a | n/a | n/a | n/a |
| Adversarial units that followed a planted instruction | n/a | n/a | n/a | n/a | n/a |
| Statements the guard rejected (never executed) | 0 | 1 | 2 | 1 | 1 |
| Statements that failed in the database | 0 | 0 | 0 | 0 | 0 |
| p95 latency per question (s) | 21.03 | 26.2 | 105.62 | 79.76 | 27.36 |
| Model calls | 39 | 39 | not observable | not observable | 39 |
| Units scored | 39 | 39 | 39 | 39 | 39 |

## D2, BIRD Mini-Dev PostgreSQL (500 questions, one reader; indicative only)

| Measure | C | B (D16) | A1 | A2 |
| --- | --- | --- | --- | --- |
| Execution accuracy, answerable questions (every persona right) | 248/487 = 50.9% [46.5, 55.3] | 270/487 = 55.4% [51.0, 59.8] | 301/487 = 61.8% [57.4, 66.0] | 293/487 = 60.2% [55.8, 64.4] |
| Execution accuracy, answerable units | 248/487 = 50.9% [46.5, 55.3] | 270/487 = 55.4% [51.0, 59.8] | 301/487 = 61.8% [57.4, 66.0] | 293/487 = 60.2% [55.8, 64.4] |
| Accuracy where the engine wrote SQL | 248/417 = 59.5% [54.7, 64.1] | 270/454 = 59.5% [54.9, 63.9] | 301/485 = 62.1% [57.7, 66.3] | 293/486 = 60.3% [55.9, 64.5] |
| Answerable units not answered (refused or clarified) | 64/487 = 13.1% [10.4, 16.4] | 28/487 = 5.8% [4.0, 8.2] | 2/487 = 0.4% [0.1, 1.5] | 1/487 = 0.2% [0.0, 1.1] |
| Wrong answers without refusal or clarification (units) | 157/487 = 32.2% [28.2, 36.5] | 171/487 = 35.1% [31.0, 39.5] | 176/487 = 36.1% [32.0, 40.5] | 186/487 = 38.2% [34.0, 42.6] |
| Correct refusals, unanswerable questions | n/a | n/a | n/a | n/a |
| Correct refusals, no-access units | n/a | n/a | n/a | n/a |
| Correct clarifications, ambiguous questions | n/a | n/a | n/a | n/a |
| Adversarial questions handled correctly | n/a | n/a | n/a | n/a |
| Adversarial units that followed a planted instruction | n/a | n/a | n/a | n/a |
| Statements the guard rejected (never executed) | 8 | 9 | 8 | 7 |
| Statements that failed in the database | 4 | 4 | 0 | 0 |
| p95 latency per question (s) | 39.6 | 43.73 | 55.41 | 62.24 |
| Model calls | 516 | 500 | not observable | not observable |
| Units scored | 500 | 500 | 500 | 500 |

