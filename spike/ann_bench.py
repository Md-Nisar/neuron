"""Exact scan vs HNSW + iterative scan, by allowed-set size (question 3). Run after ann_load.py."""
import statistics
import sys
import time

import numpy as np
import psycopg
from pgvector import HalfVector
from pgvector.psycopg import register_vector

APP = "postgresql://postgres:spike-superuser@127.0.0.1:55432/neuron"
SIZES = {1: 500, 2: 2_000, 3: 5_000, 4: 10_000, 5: 20_000, 6: 50_000, 7: 100_000}
QUERIES, CANDIDATES, K = 20, 80, 10
EF_SEARCH = int(sys.argv[1]) if len(sys.argv) > 1 else 40
rng = np.random.default_rng(7)
EXACT = ("SELECT chunk_id FROM spike_emb WHERE profile_id = 1 AND kb_id = ANY(%(kbs)s)"
         " ORDER BY (embedding::halfvec(2048) <=> %(q)s::halfvec(2048)) + 0 LIMIT %(n)s")
HNSW = ("WITH c AS MATERIALIZED (SELECT chunk_id, embedding::halfvec(2048) <=> %(q)s::halfvec(2048) AS d"
        " FROM spike_emb WHERE profile_id = 1 AND kb_id + 0 = ANY(%(kbs)s)"
        " ORDER BY embedding::halfvec(2048) <=> %(q)s::halfvec(2048) LIMIT %(n)s)"
        " SELECT chunk_id FROM c ORDER BY d")


def timed(conn: psycopg.Connection, query: str, params: dict, settings: list[str]) -> tuple[float, list[int]]:
    with conn.transaction():
        for s in settings:
            conn.execute(s)
        conn.execute(query, params).fetchall()  # warm
        t = time.perf_counter()
        rows = [r[0] for r in conn.execute(query, params).fetchall()]
        return (time.perf_counter() - t) * 1000, rows


with psycopg.connect(APP) as conn:
    register_vector(conn)
    plan_e = conn.execute("EXPLAIN " + EXACT, {"kbs": [1], "q": HalfVector(np.zeros(2048)), "n": 80}).fetchall()
    print(f"ef_search={EF_SEARCH}; exact plan: {plan_e[0][0][:60]}...")
    print("allowed  exact_p50  exact_p95  hnsw_p50  hnsw_p95  recall@10  rows_returned(min/80)")
    for kb, size in SIZES.items():
        ex_t, hn_t, recalls, returned = [], [], [], []
        ids = [r[0] for r in conn.execute("SELECT chunk_id FROM spike_emb WHERE kb_id = %s ORDER BY random()"
                                          " LIMIT %s", (kb, QUERIES)).fetchall()]
        for cid in ids:
            v = np.array(conn.execute("SELECT embedding::text FROM spike_emb WHERE chunk_id = %s", (cid,))
                         .fetchone()[0].strip("[]").split(","), dtype=np.float32)
            q = v + 0.5 * rng.standard_normal(2048).astype(np.float32) / np.sqrt(2048)
            params = {"kbs": [kb], "q": HalfVector(q / np.linalg.norm(q)), "n": CANDIDATES}
            te, exact = timed(conn, EXACT, params, ["SET LOCAL enable_indexscan = off"])
            th, hnsw = timed(conn, HNSW, params, ["SET LOCAL hnsw.iterative_scan = relaxed_order",
                                                  f"SET LOCAL hnsw.ef_search = {EF_SEARCH}",
                                                  "SET LOCAL enable_seqscan = off"])
            ex_t.append(te); hn_t.append(th); returned.append(len(hnsw))
            recalls.append(len(set(exact[:K]) & set(hnsw[:K])) / K)
        p95 = lambda xs: sorted(xs)[int(0.95 * (len(xs) - 1))]
        print(f"{size:>7}  {statistics.median(ex_t):9.1f}  {p95(ex_t):9.1f}  {statistics.median(hn_t):8.1f}"
              f"  {p95(hn_t):8.1f}  {statistics.mean(recalls):9.2f}  {min(returned):>5}")
