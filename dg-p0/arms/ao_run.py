"""Arms A1 and A2 for DG-00.05: ask Auto Ontology, save its decision in run.py's format.

  AO_LOCAL_ENV=... D3_DSN=... LLM_MODEL=... \\
    python ao_run.py <run-name> --arm=A1|A2 --dataset=d3|d1|d2 [--limit=N] [--workers=4]

Each unit is one stateless POST to Auto Ontology's gateway (/api/chat/completions, the viewer
service token): the question as asked, and as `evidence` the same caller line arms B and C get
(D3: persona, regions, "the database already limits rows"). `prediction` is off (no KumoRFM) and
`target_db` names the dataset's database. Auto Ontology runs its own SQL through its own login;
the scorer ignores those rows and re-runs the submitted SQL through the guard and the persona's
A' executor, exactly as for arms B and C.

Decision mapping (Auto Ontology has no clarify outcome):
- submitted SQL (`sql_code`) -> "sql";
- no SQL and the reply ends by asking the user something -> "clarify";
- any other reply without SQL (unconstructable, or an information answer) -> "refuse";
- an error event or HTTP failure after retries -> "unparsed".
Auto Ontology's internal model calls are not observable per request, so `requests` is None.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

import engine
import run

BASE = os.environ.get("AO_BASE", "http://127.0.0.1:3000")
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # loopback only


def token() -> str:
    env = dict(line.split("=", 1) for line in open(os.environ["AO_LOCAL_ENV"]).read().split())
    return env["AO_API_TOKEN"]


def evidence(dataset: str, persona: str, extra: str = "") -> str:
    ev = f"Today is {engine.TODAY}. Caller: {engine.caller(dataset, persona)}"
    return ev + ("\n" + extra if extra else "")


def ask(payload: dict, tok: str) -> dict:
    req = urllib.request.Request(
        BASE + "/api/chat/completions",
        method="POST",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "x-api-key": tok},
    )
    rec = {"sql": "", "response": "", "error": None, "steps": 0}
    with OPENER.open(req, timeout=900) as r:
        for raw in r:
            line = raw.decode().strip()
            if not line.startswith("data:"):
                continue
            body = line.removeprefix("data:").strip()
            if body == "[DONE]":
                break
            ev = json.loads(body)
            if ev.get("type") == "step":
                rec["steps"] += 1
            elif ev.get("type") == "result":
                a = ev.get("answer") or {}
                rec["sql"] = (a.get("sql_code") or "").strip()
                rec["response"] = str(a.get("response") or "")
            elif ev.get("type") == "error":
                rec["error"] = str(ev.get("message"))[:500]
    return rec


ASKS_BACK = re.compile(r"\?\s*(\**\s*)?$")


def decide(rec: dict) -> dict:
    if rec["sql"]:
        return {"action": "sql", "sql": rec["sql"].rstrip(";").strip()}
    if rec["error"] or not rec["response"].strip():  # an empty reply is a failed run, not a refusal
        return {"action": "unparsed"}
    text = rec["response"].strip()
    if ASKS_BACK.search(text):
        return {"action": "clarify", "text": text[:500]}
    return {"action": "refuse", "text": text[:500]}


def main(name: str, arm: str, dataset: str, limit: int | None, workers: int) -> int:
    out_dir = run.HERE / "runs" / name
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "outputs.jsonl"
    done = set()
    if path.exists():
        done = {
            (r["arm"], r["qid"], r["persona"])
            for r in map(json.loads, path.read_text().splitlines())
        }
    todo = [u for u in run.units(dataset, limit) if (arm, u["qid"], u["persona"]) not in done]
    print(f"{len(done)} done, {len(todo)} to call", flush=True)
    tok, lock, failed = token(), threading.Lock(), 0
    db = engine.DATASETS[dataset]["db"] if dataset in engine.DATASETS else None

    def one(u: dict) -> dict:
        payload = {
            "question": u["question"],
            "evidence": evidence(dataset, u["persona"], u.get("evidence", "")),
            "prediction": False,
        }
        target = u.get("db") or db
        if target:
            payload["target_db"] = target
        t0 = time.monotonic()
        for i in range(1, 4):
            try:
                rec = ask(payload, tok)
                break
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if i == 3:
                    rec = {"sql": "", "response": "", "error": f"{type(e).__name__}", "steps": 0}
                time.sleep(10 * i)
        return {
            "arm": arm,
            "dataset": dataset,
            "model": os.environ["LLM_MODEL"],
            "qid": u["qid"],
            "persona": u["persona"],
            "prompt_sha": hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[
                :16
            ],
            "raw": json.dumps(rec)[:4000],
            "decision": decide(rec),
            "seconds": round(time.monotonic() - t0, 3),
            "requests": None,
        }

    with ThreadPoolExecutor(workers) as pool, path.open("a") as fh:
        futs = {pool.submit(one, u): u for u in todo}
        for n, f in enumerate(as_completed(futs), 1):
            try:
                rec = f.result()
            except Exception as e:  # noqa: BLE001 (record and continue; a rerun retries it)
                failed += 1
                print(
                    f"FAILED {futs[f]['qid']} {futs[f]['persona']}: {type(e).__name__}: {e}",
                    flush=True,
                )
                continue
            if rec["decision"]["action"] == "unparsed":
                failed += 1
                print(f"ERROR {rec['qid']} {rec['persona']}: {rec['raw'][:200]}", flush=True)
                continue  # not written: a rerun retries it
            with lock:
                fh.write(json.dumps(rec) + "\n")
                fh.flush()
            if n % 25 == 0:
                print(f"{n}/{len(todo)}", flush=True)
    print(f"finished, {failed} failed (rerun to retry them)")
    return 1 if failed else 0


if __name__ == "__main__":
    args = dict(a.lstrip("-").split("=", 1) for a in sys.argv[2:])
    sys.exit(
        main(
            sys.argv[1],
            args["arm"],
            args.get("dataset", "d3"),
            int(args["limit"]) if "limit" in args else None,
            int(args.get("workers", "4")),
        )
    )
