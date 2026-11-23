"""Run arms C and B over a dataset's questions and save every engine output (DG-00.03).

  D3_DSN="host=... port=..." LLM_BASE_URL=... LLM_API_KEY=... LLM_MODEL=... \\
    python run.py <run-name> --dataset=d3|d1 [--arms=C,B] [--limit=N] [--workers=6]

Writes runs/<run-name>/outputs.jsonl, one line per (arm, question, persona): the prompt hash,
the raw reply, the parsed decision, seconds and requests. The file is appended to as calls
finish, and units already in it are skipped, so a stopped run resumes. Scoring (score.py) reads
only this file and the frozen expectations: it makes no model calls.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import psycopg

import engine

HERE = pathlib.Path(__file__).parent


def units(dataset: str, limit: int | None) -> list[dict]:
    """Every (question, persona) the arms must answer, in a fixed order."""
    out = []
    if dataset == "d3":
        qs = [json.loads(line) for line in (engine.DG / "d3/questions.jsonl").read_text().splitlines()]
        adv = [json.loads(line) for line in (engine.DG / "d3/adversarial.jsonl").read_text().splitlines()]
        if limit:  # a smoke run: the first N of each category, plus N adversarial questions
            qs = [q for cat in ("answerable", "unanswerable", "ambiguous")
                  for q in [x for x in qs if x["category"] == cat][:limit]]
        for q in qs:
            for persona in q["expected"]:
                out.append({"qid": q["id"], "persona": persona, "question": q["question"]})
        adv_q = [a for a in adv if "question" in a["input"]]
        for a in adv_q[:limit] if limit else adv_q:
            out.append({"qid": a["id"], "persona": a["persona"], "question": a["input"]["question"]})
    else:
        qs = [json.loads(line) for line in (engine.DG / "d1/questions.jsonl").read_text().splitlines()]
        for q in qs[:limit] if limit else qs:
            out.append({"qid": q["id"], "persona": "reader", "question": q["question"]})
    return out


def main(name: str, dataset: str, arms: list[str], limit: int | None, workers: int) -> int:
    out_dir = HERE / "runs" / name
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "outputs.jsonl"
    done = set()
    if path.exists():
        for line in path.read_text().splitlines():
            r = json.loads(line)
            done.add((r["arm"], r["qid"], r["persona"]))
    admin = psycopg.connect(os.environ["D3_DSN"] + f" dbname={engine.DATASETS[dataset]['db']} user=postgres")
    ctx: dict = {}
    todo = []
    for arm in arms:
        for u in units(dataset, limit):
            if (arm, u["qid"], u["persona"]) not in done:
                todo.append({**u, "arm": arm, "dataset": dataset,
                             "prompt": engine.build_prompt(arm, dataset, u["persona"], u["question"], ctx, admin)})
    admin.close()
    print(f"{len(done)} done, {len(todo)} to call", flush=True)
    lock, failed = threading.Lock(), 0

    def one(u: dict) -> dict:
        text, secs, reqs = engine.call_model(u["prompt"])
        return {"arm": u["arm"], "dataset": dataset, "qid": u["qid"], "persona": u["persona"],
                "prompt_sha": engine.sha(u["prompt"]), "raw": text, "decision": engine.parse(text),
                "seconds": round(secs, 3), "requests": reqs}

    with ThreadPoolExecutor(workers) as pool, path.open("a") as fh:
        futs = {pool.submit(one, u): u for u in todo}
        for n, f in enumerate(as_completed(futs), 1):
            try:
                rec = f.result()
            except Exception as e:  # noqa: BLE001 (record and continue; a rerun retries it)
                failed += 1
                print(f"FAILED {futs[f]['arm']} {futs[f]['qid']} {futs[f]['persona']}: {type(e).__name__}", flush=True)
                continue
            with lock:
                fh.write(json.dumps(rec) + "\n")
                fh.flush()
            if n % 50 == 0:
                print(f"{n}/{len(todo)}", flush=True)
    print(f"finished, {failed} failed (rerun to retry them)")
    return 1 if failed else 0


if __name__ == "__main__":
    args = dict(a.lstrip("-").split("=", 1) for a in sys.argv[2:])
    sys.exit(main(sys.argv[1], args.get("dataset", "d3"), args.get("arms", "C,B").split(","),
                  int(args["limit"]) if "limit" in args else None, int(args.get("workers", "6"))))
