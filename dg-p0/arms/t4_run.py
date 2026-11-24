"""Arm T4, live (D26): B decides and names the values, the gateway checks them, A2 writes.

  D3_DSN=... AO_LOCAL_ENV=... LLM_BASE_URL=... LLM_API_KEY=... LLM_MODEL=... \\
    [D3_QUESTIONS=fresh.jsonl] python t4_run.py <run-name> [--limit=N] [--workers=2] [--sample=live-sample.json]

Per (question, persona), in order, every step measured:
1. Arm B (BP: the Ossie model plus the caller's physical columns) with one addition to its prompt:
   when it would answer, it also lists the named values the question depends on (the v2 extraction
   of valuegate.py, folded into the same call). Same model, temperature 0.
2. B refuses, clarifies or is unparsed -> that is T4's decision.
3. Otherwise the gateway looks each value up (valuegate v3: any listed text column, under the
   persona, through the reference guard and executor). A value with no row -> refuse, naming it.
4. Otherwise one call to Auto Ontology with the certified D3 model (A2), as ao_run.py asks it.
   A failed A2 run (error, empty, or no step taken: rate limits, F15) is retried; if it still
   fails, the unit is not written and a rerun asks it again.

`seconds` is measured and sequential (B + check + A2). `seconds_parallel` is computed from the
measured steps for a gateway that starts A2 together with B: max(B + check, A2) when A2 is used.
Outputs go to runs/<run-name>/outputs.jsonl in run.py's format, so score.py scores them unchanged.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import ao_run
import engine
import psycopg
import run
import score
import valuegate

valuegate.V3 = True
ARM = "T4L"
FOLD = """
When your action is "sql", also list in "values" every specific named value the question depends on
that must exist in the data for the question to have an answer: a person, product, customer,
country, region, skill, certification, category, status or similar name. Do not list numbers,
dates, periods, measures or generic words ("customers", "revenue"). For each value give the physical
table (schema.table), the column or columns that would contain it, exactly as named in the physical
schema, and the value as the column stores it, using the semantic model's descriptions where they
say how values are written (singular form, code, abbreviation); leave out words that only name the
kind of thing, such as "certification" or "customers". Use "values": [] when there is none:
{{"action": "sql", "sql": "<statement>", "values": [{{"text": "<value as written in the question>", "stored": "<value as stored>", "table": "<schema.table>", "columns": ["<column>"]}}]}}

Question: {question}"""


def prompt(persona: str, question: str, ctx: dict, admin: psycopg.Connection) -> str:
    base = engine.build_prompt("BP", "d3", persona, question, ctx, admin)
    head, sep, _ = base.rpartition("\nQuestion: ")
    assert sep, "arm B's prompt no longer ends with the question"
    return head + "\n" + FOLD.format(question=question)


CANNED = "I couldn't write a query"  # Auto Ontology's reply after model_error or budget_exhausted


def ask_a2(u: dict, tok: str) -> tuple[dict, dict, float]:
    """A2's decision, its raw reply, and the seconds of the attempt whose answer is used.

    The canned no-query reply follows both a rate-limited episode (model_error, F15) and a genuine
    budget_exhausted one, so it is asked again; only if it persists is it taken as a refusal.
    Waits between attempts are not counted as latency; `attempts` is recorded instead."""
    payload = {
        "question": u["question"],
        "evidence": ao_run.evidence("d3", u["persona"]),
        "prediction": False,
        "target_db": "d3",
    }
    for i in range(1, 7):
        t0 = time.monotonic()
        try:
            rec = ao_run.ask(payload, tok)
        except (OSError, TimeoutError) as e:
            rec = {"sql": "", "response": "", "error": type(e).__name__, "steps": 0}
        secs = time.monotonic() - t0
        rec["attempts"] = i
        decision = ao_run.decide(rec)
        retry = decision["action"] == "unparsed" or (
            decision["action"] == "refuse" and decision["text"].startswith(CANNED) and i < 6
        )
        if not retry:
            return decision, rec, secs
        time.sleep(min(300, 30 * i))  # rate limited or failed: wait, then ask again
    return {"action": "unparsed"}, rec, secs


def main(name: str, limit: int | None, workers: int, sample: str | None = None) -> int:
    path = run.HERE / "runs" / name / "outputs.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    done = (
        {(r["qid"], r["persona"]) for r in map(json.loads, path.read_text().splitlines())}
        if path.exists()
        else set()
    )
    keep = set(json.loads((engine.DG / "d3" / sample).read_text())["qids"]) if sample else None
    todo = [u for u in run.units("d3", limit)
            if (u["qid"], u["persona"]) not in done and (keep is None or u["qid"] in keep)]
    ctx: dict = {}
    with psycopg.connect(os.environ["D3_DSN"] + " dbname=d3 user=postgres") as admin:
        scopes = {n: score.guard_scope(admin, p) for n, p in score.PERSONAS.items()}
        for u in todo:
            u["prompt"] = prompt(u["persona"], u["question"], ctx, admin)
    print(f"{len(done)} done, {len(todo)} to call ({engine.D3_QUESTIONS})", flush=True)
    tok, lock, failed = ao_run.token(), threading.Lock(), 0

    def one(u: dict) -> dict | None:
        text, b_secs, reqs = engine.call_model(u["prompt"], attempts=8)
        b = engine.parse(text)
        rec = {
            "arm": ARM,
            "dataset": "d3",
            "model": os.environ["LLM_MODEL"],
            "qid": u["qid"],
            "persona": u["persona"],
            "prompt_sha": engine.sha(u["prompt"]),
            "raw": text[:4000],
            "b_decision": b,
            "b_seconds": round(b_secs, 3),
            "requests": reqs,
        }
        if b["action"] != "sql":
            return {
                **rec,
                "decision": b,
                "routed_to": "B",
                "seconds": round(b_secs, 3),
                "seconds_parallel": round(b_secs, 3),
            }
        values = valuegate.parse(text)
        t0 = time.monotonic()
        c = valuegate.check("d3", u["persona"], values, scopes, None)
        look = time.monotonic() - t0
        rec |= {"values": values, "lookups": c["lookups"], "check_seconds": round(look, 3)}
        if c["verdict"] == "refuse":
            secs = b_secs + look
            return {
                **rec,
                "decision": {"action": "refuse", "text": c["reason"]},
                "routed_to": "value_check",
                "seconds": round(secs, 3),
                "seconds_parallel": round(secs, 3),
            }
        a2, raw, a2_secs = ask_a2(u, tok)
        if a2["action"] == "unparsed":
            return None  # A2 kept failing: not written, a rerun asks again
        return {
            **rec,
            "decision": a2,
            "routed_to": "A2",
            "a2_raw": json.dumps(raw)[:4000],
            "a2_seconds": round(a2_secs, 3),
            "seconds": round(b_secs + look + a2_secs, 3),
            "seconds_parallel": round(max(b_secs + look, a2_secs), 3),
        }

    with ThreadPoolExecutor(workers) as pool, path.open("a") as fh:
        futs = {pool.submit(one, u): u for u in todo}
        for n, f in enumerate(as_completed(futs), 1):
            u = futs[f]
            try:
                rec = f.result()
            except Exception as e:  # noqa: BLE001 (record and continue; a rerun retries it)
                rec, why = None, f"{type(e).__name__}: {e}"[:200]
            else:
                why = "A2 kept failing"
            if rec is None:
                failed += 1
                print(f"FAILED {u['qid']} {u['persona']}: {why}", flush=True)
                continue
            with lock:
                fh.write(json.dumps(rec) + "\n")
                fh.flush()
            if n % 25 == 0:
                print(f"{n}/{len(todo)}", flush=True)
    print(f"finished, {failed} failed (rerun to retry them)", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    args = dict(a.lstrip("-").split("=", 1) for a in sys.argv[2:])
    sys.exit(
        main(
            sys.argv[1],
            int(args["limit"]) if "limit" in args else None,
            int(args.get("workers", "2")),
            args.get("sample"),
        )
    )
