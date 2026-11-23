"""Freeze one batch of D3 questions and run the independent second annotator (DG-00.01, D3).

  D3_DSN="host=... port=..." LLM_BASE_URL=... LLM_API_KEY=... LLM_MODEL=... \
    python batch.py sales-01

Reads batches/<name>.src.jsonl (id, category, question, reference_sql, optional order_matters).
For each question and persona it records the reference answer as `expected` (rows, or the error
class when the persona may not read a table). A second model, which sees the question and the
schema but never the reference SQL, writes its own query; its answers are compared with the
reference per persona. Writes batches/<name>.jsonl and batches/<name>.md for owner review.

The annotator's SQL runs only through check.run_as: one statement, read-only transaction, the
persona's data role, row-level security. The API key is read from the environment and never
printed. `python batch.py <name> --accept [--alt=ID,ID]` appends an owner-accepted batch to
questions.jsonl, which check.py then verifies on every run; --alt keeps the second annotator's
answer as an accepted alternative form. Previous annotator SQL is reused if the output file
exists (pass --fresh to re-ask).
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from itertools import permutations
from decimal import Decimal

import psycopg

from check import HERE, PERSONAS, run_as

SCHEMA_FILES = {"S": "sql/01_sales_schema.sql", "K": "sql/02_skills_schema.sql"}
PROMPT = """You write PostgreSQL 16 queries for a reporting database. Schema:

{schema}

Rules: revenue means the net line amount of completed orders unless the question says otherwise.
Write exactly one SELECT statement answering the question. Return the columns in the order the
question mentions them. Round only if the question asks. Reply with the SQL only, no prose.

Question: {question}"""


def ask_model(question: str, schema: str) -> str:
    body = {
        "model": os.environ["LLM_MODEL"],
        "messages": [{"role": "user", "content": PROMPT.format(schema=schema, question=question)}],
        "temperature": 0,
        "max_tokens": 4000,
    }
    req = urllib.request.Request(
        os.environ["LLM_BASE_URL"].rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={
            "Authorization": "Bearer " + os.environ["LLM_API_KEY"],
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=300) as resp:  # noqa: S310 (fixed https endpoint)
        text = json.load(resp)["choices"][0]["message"]["content"] or ""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    m = re.search(r"```(?:sql)?\s*(.*?)```", text, flags=re.S)
    return (m.group(1) if m else text).strip().rstrip(";").strip()


def answer(persona: dict, sql: str) -> dict:
    try:
        cols, rows = run_as(persona, sql)
    except psycopg.Error as e:
        return {"error": type(e).__name__}
    plain = [[float(v) if isinstance(v, Decimal) else v for v in r] for r in rows]
    return {"columns": cols, "rows": plain}


def same_rows(got: list, exp: list, order_matters: bool) -> bool:
    """Equal row sets, numbers within 0.01 (the reference rounds money to cents; the annotator
    may not). Significant-digit bucketing is not used: it splits values half a cent apart."""
    if len(got) != len(exp):
        return False
    key = lambda r: [(0, v, "") if isinstance(v, (int, float)) else (1, 0, str(v)) for v in r]  # noqa: E731
    if not order_matters:
        got, exp = sorted(got, key=key), sorted(exp, key=key)
    for g, e in zip(got, exp):
        for a, b in zip(g, e):
            num = isinstance(a, (int, float)) and isinstance(b, (int, float))
            if not (abs(a - b) <= 0.01 if num else str(a) == str(b)):
                return False
    return True


def agree(exp: dict, got: dict, order_matters: bool) -> tuple[bool, str]:
    if "error" in exp or "error" in got:
        same = exp.get("error") == got.get("error")
        return same, "same error" if same else f"{exp.get('error', 'rows')} vs {got.get('error', 'rows')}"
    if len(got["columns"]) < len(exp["columns"]):
        return False, f"{len(got['columns'])} columns vs {len(exp['columns'])}"
    if len(got["rows"]) != len(exp["rows"]):
        return False, f"{len(got['rows'])} rows vs {len(exp['rows'])}"
    # Column names differ between annotators, so match by position. The same values in another
    # column order, or with extra columns (an id beside a name), count as agreement.
    n, k = len(got["columns"]), len(exp["columns"])
    for perm in permutations(range(n), k):
        rows = [[r[i] for i in perm] for r in got["rows"]]
        if same_rows(rows, exp["rows"], order_matters):
            if n > k:
                return True, "ok (extra columns)"
            return True, "ok" if list(perm) == sorted(perm) else "ok (columns reordered)"
    return False, "values differ"


def show(a: dict, limit: int = 6) -> str:
    if "error" in a:
        return f"refused ({a['error']})"
    rows = a["rows"]
    body = "; ".join(", ".join(str(v) for v in r) for r in rows[:limit])
    more = f" … (+{len(rows) - limit} rows)" if len(rows) > limit else ""
    return f"{', '.join(a['columns'])} → {body or 'no rows'}{more}"


def main(name: str, fresh: bool) -> int:
    src = [json.loads(x) for x in (HERE / f"batches/{name}.src.jsonl").read_text().splitlines() if x]
    out_path = HERE / f"batches/{name}.jsonl"
    old = {}
    if out_path.exists() and not fresh:
        old = {q["id"]: q for q in map(json.loads, out_path.read_text().splitlines())}
    out, md, disagreements = [], [f"# Batch {name}: owner review\n"], 0
    for q in src:
        schema = (HERE / SCHEMA_FILES[q["id"][0]]).read_text()
        prev = old.get(q["id"], {})
        second = prev.get("second_sql") if prev.get("question") == q["question"] else None
        second = second or ask_model(q["question"], schema)
        om = q.get("order_matters", False)
        rec = {**q, "order_matters": om, "expected": {}, "second_sql": second, "agreement": {}}
        lines = [f"## {q['id']}: {q['question']}\n", f"Reference:\n```sql\n{q['reference_sql']}\n```",
                 f"Second annotator:\n```sql\n{second}\n```", "| Persona | Reference answer | Agree |",
                 "| --- | --- | --- |"]
        for pname, p in PERSONAS.items():
            exp = answer(p, q["reference_sql"])
            got = answer(p, second)
            ok, why = agree(exp, got, om)
            rec["expected"][pname] = exp
            rec["agreement"][pname] = {"agree": ok, "why": why, "second": got}
            lines.append(f"| {pname} | {show(exp)} | {'yes' if ok else 'NO: ' + why} |")
            if not ok:
                lines.append(f"| | second: {show(got)} | |")
        if not all(a["agree"] for a in rec["agreement"].values()):
            disagreements += 1
            lines.append("\n**Disagreement: owner to adjudicate.**")
        md += lines + [""]
        out.append(rec)
        print(q["id"], "agree" if all(a["agree"] for a in rec["agreement"].values()) else "DISAGREE")
    md.insert(1, f"{len(src)} questions, {len(src) - disagreements} agree on every persona, "
                 f"{disagreements} to adjudicate.\n")
    out_path.write_text("".join(json.dumps(r, default=str) + "\n" for r in out))
    (HERE / f"batches/{name}.md").write_text("\n".join(md))
    return 0


def accept(name: str, alt: set[str]) -> int:
    """Owner accepted the batch: append its questions, with reference answers, to questions.jsonl.

    For ids in `alt`, the owner also accepted the second annotator's answer as an equally correct
    form (for example months as dates rather than numbers); it is kept as `alternatives`.
    """
    path = HERE / "questions.jsonl"
    have = {json.loads(x)["id"] for x in path.read_text().splitlines() if x} if path.exists() else set()
    keep = ("id", "category", "question", "reference_sql", "order_matters", "expected")
    batch = list(map(json.loads, (HERE / f"batches/{name}.jsonl").read_text().splitlines()))
    if unknown := alt - {q["id"] for q in batch}:
        sys.exit(f"--alt names questions not in this batch: {sorted(unknown)}")
    with path.open("a") as f:
        for q in batch:
            if q["id"] in have:
                sys.exit(f"{q['id']} is already in questions.jsonl")
            rec = {k: q[k] for k in keep}
            if q["id"] in alt:
                rec["alternatives"] = [{p: a["second"] for p, a in q["agreement"].items()}]
            f.write(json.dumps(rec, default=str) + "\n")
    return 0


if __name__ == "__main__":
    if "--accept" in sys.argv:
        alt = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--alt=")), "")
        sys.exit(accept(sys.argv[1], set(filter(None, alt.split(",")))))
    sys.exit(main(sys.argv[1], "--fresh" in sys.argv))
