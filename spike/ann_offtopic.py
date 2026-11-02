"""HNSW underfill for off-topic (random) queries on small allowed sets (question 3). Run after ann_load.py."""
import os
import statistics
import time

import numpy as np
import psycopg
from pgvector import HalfVector
from pgvector.psycopg import register_vector

APP = "postgresql://postgres:spike-superuser@127.0.0.1:55432/neuron"
DIM = int(os.environ.get("SPIKE_DIM", "1024"))
HNSW = (f"WITH c AS MATERIALIZED (SELECT chunk_id, embedding::halfvec({DIM}) <=> %(q)s::halfvec({DIM}) AS d"
        " FROM spike_emb WHERE profile_id = 1 AND kb_id + 0 = ANY(%(kbs)s)"
        f" ORDER BY embedding::halfvec({DIM}) <=> %(q)s::halfvec({DIM}) LIMIT %(n)s)"
        " SELECT chunk_id FROM c ORDER BY d")
SETTINGS = ["SET LOCAL jit = off", "SET LOCAL hnsw.iterative_scan = relaxed_order", "SET LOCAL hnsw.ef_search = 100",
            "SET LOCAL enable_seqscan = off", "SET LOCAL enable_bitmapscan = off", "SET LOCAL enable_sort = off"]
rng = np.random.default_rng(3)
with psycopg.connect(APP) as conn:
    register_vector(conn)
    print("allowed  hnsw_p50  rows_returned(min/80)  mean")
    for kb, size in [(1, 500), (2, 2_000), (3, 5_000), (4, 10_000), (5, 20_000)]:
        ts, rows = [], []
        for _ in range(10):
            q = rng.standard_normal(DIM).astype(np.float32)
            with conn.transaction():
                for s in SETTINGS:
                    conn.execute(s)
                t = time.perf_counter()
                rows.append(len(conn.execute(HNSW, {"kbs": [kb], "q": HalfVector(q / np.linalg.norm(q)),
                                                    "n": 80}).fetchall()))
                ts.append((time.perf_counter() - t) * 1000)
        print(f"{size:>7}  {statistics.median(ts):8.1f}  {min(rows):>5}  {statistics.mean(rows):5.1f}")
