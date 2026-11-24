"""Opportunity 1 (research follow-up to DG-00.07): "triage, then write", estimated offline.

  python triage.py            # writes runs/tri-<ds>/outputs.jsonl for d3, d1, d2
  D3_DSN=... python score.py tri-d3   (and tri-d1, tri-d2)

No model is called. Arm T routes each (question, persona) unit using decisions already saved:
arm B (D16) decides first; if B refuses or asks to clarify, T returns B's decision; if B would
answer, T returns arm A2's decision for the same unit (SQL, or A2's own refusal). The scorer is
unchanged, so T is judged exactly as every other arm.

Latency is not observable for T; two estimates are recorded per unit:
  seconds            sequential: B's time, plus A2's time when B answers (the gate waits for B);
  seconds_parallel   B and A2 started together: B's time if B stops, else the slower of the two.
Caveat: this assumes each engine would decide the same way inside the composite as it did alone.
"""

from __future__ import annotations

import json
import pathlib

HERE = pathlib.Path(__file__).parent
PAIRS = {"d3": ("bp-d3", "ao-d3-a2"), "d1": ("bp-d1", "ao-d1-a2"), "d2": ("cb-d2", "ao-d2-a2")}


def load(run: str, arm: str) -> dict:
    recs = (
        json.loads(line)
        for line in (HERE / "runs" / run / "outputs.jsonl").read_text().splitlines()
    )
    return {(r["qid"], r["persona"]): r for r in recs if r["arm"] == arm}


def compose(ds: str) -> list[dict]:
    b_run, a_run = PAIRS[ds]
    b, a = load(b_run, "BP"), load(a_run, "A2")
    if b.keys() != a.keys():
        raise SystemExit(f"{ds}: B and A2 cover different units ({len(b)} against {len(a)})")
    out = []
    for key in sorted(b):
        rb, ra = b[key], a[key]
        gate_answers = rb["decision"]["action"] == "sql"
        src = ra if gate_answers else rb
        out.append(
            {
                "arm": "T",
                "dataset": ds,
                "qid": key[0],
                "persona": key[1],
                "model": src.get("model", "unrecorded"),
                "decision": src["decision"],
                "routed_to": "A2" if gate_answers else "B",
                "seconds": round(rb["seconds"] + (ra["seconds"] if gate_answers else 0.0), 3),
                "seconds_parallel": round(
                    max(rb["seconds"], ra["seconds"]) if gate_answers else rb["seconds"], 3
                ),
                "requests": None,
            }
        )
    return out


if __name__ == "__main__":
    for ds in PAIRS:
        recs = compose(ds)
        run = HERE / "runs" / f"tri-{ds}"
        run.mkdir(exist_ok=True)
        (run / "outputs.jsonl").write_text(
            "".join(json.dumps(r, sort_keys=True) + "\n" for r in recs)
        )
        to_a2 = sum(r["routed_to"] == "A2" for r in recs)
        print(f"{ds}: {len(recs)} units, {to_a2} routed to A2, {len(recs) - to_a2} stopped by B")
