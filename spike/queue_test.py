"""Kill-worker test for one queue library (RAG-00.02 question 4). Usage: queue_test.py LIB."""
import os
import signal
import subprocess
import sys
import time

import psycopg

from queue_common import APP_DSN, MIGRATOR_DSN

LIB = sys.argv[1]
PY = ".venv/bin/python"
WORKER = [PY, f"queue_{LIB}.py", "worker"]
LOG = open(f"queue_{LIB}.log", "w")
GRANTS = """
GRANT USAGE ON SCHEMA public TO neuron_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO neuron_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO neuron_app;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO neuron_app;
"""


def sql(dsn: str, query: str, args: tuple | None = None) -> list:
    with psycopg.connect(dsn, autocommit=True) as conn:
        cur = conn.execute(query, args)
        return cur.fetchall() if cur.description else []


def install() -> None:
    sql(MIGRATOR_DSN, "CREATE TABLE IF NOT EXISTS spike_effects (lib text, doc_id int, pid int,"
        " phase text, at timestamptz DEFAULT clock_timestamp())")
    sql(MIGRATOR_DSN, "CREATE TABLE IF NOT EXISTS spike_done (lib text, doc_id int,"
        " PRIMARY KEY (lib, doc_id))")
    if LIB == "procrastinate":
        if not sql(MIGRATOR_DSN, "SELECT 1 FROM pg_tables WHERE tablename='procrastinate_jobs'"):
            schema = subprocess.run([PY, "-c", "from procrastinate import schema;"
                                     "print(schema.SchemaManager.get_schema())"],
                                    capture_output=True, text=True, check=True).stdout
            sql(MIGRATOR_DSN, schema)
    else:
        if not sql(MIGRATOR_DSN, "SELECT 1 FROM pg_tables WHERE tablename='pgqueuer'"):
            subprocess.run([PY, "-m", "pgqueuer", "--pg-dsn", MIGRATOR_DSN, "install"],
                           check=True, capture_output=True)
    sql(MIGRATOR_DSN, GRANTS)


def effects(phase: str, first: int, last: int) -> dict[int, int]:
    rows = sql(APP_DSN, "SELECT doc_id, count(*) FROM spike_effects WHERE lib=%s AND phase=%s"
               " AND doc_id BETWEEN %s AND %s GROUP BY doc_id", (LIB, phase, first, last))
    return dict(rows)


def wait_for(predicate, timeout: float) -> float:
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        if predicate():
            return time.monotonic() - start
        time.sleep(0.5)
    raise TimeoutError


def defer(n: int, first: int) -> None:
    subprocess.run([PY, f"queue_{LIB}.py", "defer", str(n), str(first)], check=True)


def main() -> None:
    install()
    if LIB == "pgqueuer":
        sql(MIGRATOR_DSN, "TRUNCATE pgqueuer, pgqueuer_log")
    else:
        sql(MIGRATOR_DSN, "TRUNCATE procrastinate_jobs CASCADE")
    sql(APP_DSN, "DELETE FROM spike_effects WHERE lib=%s", (LIB,))
    sql(APP_DSN, "DELETE FROM spike_done WHERE lib=%s", (LIB,))
    # 1. Six jobs; doc 1 fails once on purpose. Kill the worker while jobs are mid-run.
    defer(6, 1)
    a = subprocess.Popen(WORKER, stdout=LOG, stderr=LOG)
    wait_for(lambda: sum(effects("start", 2, 6).values()) >= 2, 60)
    a.send_signal(signal.SIGKILL)
    a.wait()
    killed_mid_run = sorted(set(effects("start", 1, 6)) - set(effects("finish", 1, 6)))
    # 2. Restart: every job must finish, and the completion write must happen once per doc.
    b = subprocess.Popen(WORKER, stdout=LOG, stderr=LOG)
    t0 = time.monotonic()
    recovered_after = wait_for(lambda: len(sql(APP_DSN, "SELECT 1 FROM spike_done WHERE lib=%s"
                                               " AND doc_id BETWEEN 1 AND 6", (LIB,))) == 6, 180)
    b.send_signal(signal.SIGTERM)
    b.wait(timeout=60)
    # 3. Graceful drain: SIGTERM while two jobs run; they should finish before the worker exits.
    defer(2, 101)
    c = subprocess.Popen(WORKER, stdout=LOG, stderr=LOG)
    wait_for(lambda: sum(effects("start", 101, 102).values()) == 2, 60)
    c.send_signal(signal.SIGTERM)
    t1 = time.monotonic()
    code = c.wait(timeout=120)
    drained = effects("finish", 101, 102)
    print(f"lib={LIB}")
    print(f"killed with jobs mid-run: docs {killed_mid_run}")
    print(f"all 6 done {recovered_after:.1f}s after restart (restart at t={t0:.0f})")
    print(f"starts per doc: {dict(sorted(effects('start', 1, 6).items()))}")
    print(f"finishes per doc: {dict(sorted(effects('finish', 1, 6).items()))}")
    print(f"retry of doc 1 after failure: fail={effects('fail', 1, 1)}")
    print(f"drain: exit code {code} after {time.monotonic() - t1:.1f}s, finished {drained}")
    if LIB == "procrastinate":
        print("job status:", sql(APP_DSN, "SELECT status, count(*) FROM procrastinate_jobs"
                                 " WHERE task_name='ingest' GROUP BY status"))
    else:
        print("queue rows left:", sql(APP_DSN, "SELECT status, count(*) FROM pgqueuer GROUP BY status"))
        print("log:", sql(APP_DSN, "SELECT status, count(*) FROM pgqueuer_log"
                          " WHERE entrypoint='ingest' GROUP BY status"))


main()
