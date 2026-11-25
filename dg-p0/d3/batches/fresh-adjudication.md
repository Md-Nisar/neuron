# Fresh D3 set (D26): owner adjudication

Written and frozen before any live result on it. 80 questions (40 answerable, 40 unanswerable), 240
question-persona units. Second annotator: same model, schema only (batch.py), as for D3.

14 disagreements, all decided for the reference; no alternatives accepted.

| Question | Second annotator | Decision |
| --- | --- | --- |
| S-FA-10 | `p.name = 'Edge Servers'` (no row) | Reference: the product is stored as "Edge Server". |
| S-FA-13 | `ILIKE '%27-inch%monitor%'` (no row) | Reference: stored as "Monitor 27in". |
| K-FA-13 | `ILIKE 'ITIL'` (no row) | Reference: stored as "ITIL Foundation". |
| S-FU-01, 02, 05, 06, 07 | answer or clarify | Refuse: the named value does not exist (evidence query returns 0); the schema-only annotator cannot see values. |
| K-FU-01, 02, 03, 05, 07 | answer or clarify | Refuse, same reason. |
| K-FU-04 | answer 0: the job_title CHECK excludes Director | Refuse, consistent with D3's K-U-022 ("How many Directors are there?"). |

S-FA-01 disagreed on the first pass and agreed on the rerun after the 429 retries were added.

Hashes (sha256): fresh.jsonl 8435d17aaa44a3f089c9a5b6fd0b29359af83d57b9f89cd16b4ceb8161649303;
sources fresh-sales-a c440f68b…, fresh-sales-u 33ffe237…, fresh-skills-a f882d298…, fresh-skills-u 13abb492….

## D28 (2026-11-25): owner rule on values outside the caller's regions

Owner: "value outside region shall respond with refuse". `d3/scope_rule.py` applied it to both
question files: a persona's expectation becomes a refusal (`{"error": "OutOfScopeValue", "hidden":
[...], "was": <old expectation>}`, the scorer's existing no-access form) when a text value the
reference SQL names sits only in regions outside the persona's. 16 fresh units and 2 D3 units
changed (`d28-scope-rule.txt`); every one previously expected 0 or empty. Before: fresh.jsonl
8435d17a…, questions.jsonl 422cffeb…. After: fresh.jsonl
19b0a7f4fb9795e36b2512ce5b0a32794a671395ff9cd99a642a382153735b7a, questions.jsonl
c7e59023927d5bbb0b57c82633ae7ad40ace1f2f1f5bacdd5c13467f3899a310. Scores made before D28 stay as
recorded; rescored copies are the `-d28` runs.
