"""D28: replay a live T4 run through the value check v4, with no model calls.

Each unit that got past B carries the values B listed. They are looked up again with v4 (v3 plus
the region step). A unit v4 refuses becomes a refusal routed to the value check; every other unit
keeps its recorded decision, since B's output and the values are unchanged and v4 only adds
refusals. Latency fields are kept as recorded.

  python arms/t4_v4.py t4l-fresh     # writes runs/t4l-fresh-v4/outputs.jsonl
"""

from __future__ import annotations

import json
import pathlib
import sys

import psycopg
import score
import valuegate

valuegate.V3 = valuegate.V4 = True
HERE = pathlib.Path(__file__).resolve().parent


def main(src: str) -> None:
    recs = [
        json.loads(line)
        for line in (HERE / "runs" / src / "outputs.jsonl").read_text().splitlines()
    ]
    with psycopg.connect(f"{score.DSN} dbname=d3 user=postgres") as admin:
        scopes = {n: score.guard_scope(admin, p) for n, p in score.PERSONAS.items()}
    changed = []
    for r in recs:
        if r["routed_to"] == "B":  # B refused or clarified: the check never ran
            continue
        # Live runs record the values; the offline T4 run (tri4) records them inside its lookups.
        values = r.get("values") or [
            {k: v for k, v in x.items() if k not in ("state", "code")} for x in r["lookups"]
        ]
        c = valuegate.check("d3", r["persona"], values, scopes, None)
        if c["verdict"] == "refuse" and r["routed_to"] != "value_check":
            changed.append(
                f"{r['qid']} {r['persona']}: {r['decision']['action']} -> refuse ({c['reason']})"
            )
            r.update(
                lookups=c["lookups"],
                decision={"action": "refuse", "text": c["reason"]},
                routed_to="value_check",
            )
        elif r["routed_to"] == "value_check" and c["verdict"] != "refuse":
            raise SystemExit(f"v4 passed what v3 refused: {r['qid']} {r['persona']}")
    out = HERE / "runs" / f"{src}-v4"
    out.mkdir(exist_ok=True)
    (out / "outputs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs))
    (out / "changed.txt").write_text("".join(line + "\n" for line in changed))
    print(f"{src}: {len(changed)} decisions changed", *changed, sep="\n")


if __name__ == "__main__":
    main(sys.argv[1])
