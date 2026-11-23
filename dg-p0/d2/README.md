# D2: BIRD Mini-Dev, PostgreSQL edition (DG-00.05)

Source: BIRD Mini-Dev (`minidev.zip` from `bird-bench.oss-cn-beijing.aliyuncs.com`, sha256
`cc48ba16838204e4e214512030cb572eeb5f7bcdd999bae4b9b6ff12ec13b92f`; bird-bench/mini_dev), CC BY-SA 4.0.
`questions.jsonl` holds BIRD's questions, evidence and gold SQL with the frozen results of that SQL here.

D2 is indicative only: BIRD's labels are known to be noisy (ADR 0016).

| File | Purpose |
| --- | --- |
| `load.sh` | One database per BIRD database (`d2_<db_id>`), logins `d2_reader` and `d2_ao_reader`, read-only, 15 s |
| `freeze.py` | Runs the 500 gold queries as `d2_reader` and writes `questions.jsonl` (`B-001` to `B-500` by position; BIRD repeats two ids) and `excluded.json` |
| `gen_ossie.py` | One Ossie model per database, generated from BIRD's column descriptions and keys, for arms B and A2 |
| `ossie/` | The 11 generated models (valid against the pinned Ossie) |

Steps: `BIRD_SRC=<unzipped minidev> ./load.sh`, then `D3_DSN=... BIRD_SRC=... python freeze.py` and
`python gen_ossie.py` (PyYAML and psycopg).
