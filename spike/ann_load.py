"""Load synthetic clustered halfvec({DIM}) embeddings for the exact-vs-HNSW benchmark (question 3)."""
import os
import time

import numpy as np
import psycopg
from pgvector import HalfVector
from pgvector.psycopg import register_vector

SU = "postgresql://postgres:spike-superuser@127.0.0.1:55432/neuron"
DIM = int(os.environ.get("SPIKE_DIM", "1024"))
# kb_id -> chunk count. The measured sizes, plus 25 filler KBs of 500 (200,000 rows in total).
SIZES = {1: 500, 2: 2_000, 3: 5_000, 4: 10_000, 5: 20_000, 6: 50_000, 7: 100_000}
SIZES |= {100 + i: 500 for i in range(25)}
rng = np.random.default_rng(14)


def kb_vectors(n: int) -> np.ndarray:
    # A KB is a few topics: cluster centres plus noise, normalised (cosine).
    centres = rng.standard_normal((max(2, n // 250), DIM)).astype(np.float32)
    x = centres[rng.integers(0, len(centres), n)] + 0.6 * rng.standard_normal((n, DIM)).astype(np.float32)
    return x / np.linalg.norm(x, axis=1, keepdims=True)


with psycopg.connect(SU, autocommit=True) as conn:
    register_vector(conn)
    conn.execute("DROP TABLE IF EXISTS spike_emb")
    conn.execute("CREATE TABLE spike_emb (chunk_id bigint PRIMARY KEY, profile_id smallint NOT NULL,"
                 " kb_id int NOT NULL, embedding halfvec NOT NULL)")
    t, next_id = time.monotonic(), 0
    with conn.cursor().copy("COPY spike_emb FROM STDIN WITH (FORMAT BINARY)") as copy:
        copy.set_types(["int8", "int2", "int4", "halfvec"])
        for kb, n in SIZES.items():
            for v in kb_vectors(n):
                copy.write_row((next_id, 1, kb, HalfVector(v)))
                next_id += 1
    print(f"loaded {next_id} rows in {time.monotonic() - t:.0f}s")
    conn.execute("CREATE INDEX spike_emb_kb ON spike_emb (profile_id, kb_id)")
    conn.execute("SET maintenance_work_mem = '3GB'")
    conn.execute("SET max_parallel_maintenance_workers = 3")
    t = time.monotonic()
    conn.execute(f"CREATE INDEX spike_emb_hnsw ON spike_emb USING hnsw"
                 f" ((embedding::halfvec({DIM})) halfvec_cosine_ops) WHERE profile_id = 1")
    print(f"HNSW build (m=16, ef_construction=64, 4 workers) {time.monotonic() - t:.0f}s")
    conn.execute("VACUUM ANALYZE spike_emb")
    print(conn.execute("SELECT pg_size_pretty(pg_relation_size('spike_emb')),"
                       " pg_size_pretty(pg_relation_size('spike_emb_hnsw'))").fetchone())
