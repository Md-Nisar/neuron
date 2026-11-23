"""DG-00.05 results table: every arm on every dataset, from the scored runs. No model is called.

  python results.py > runs/results.md

Reads runs/<run>/score.json for the runs listed in RUNS (each scored by score.py) and writes one
table per dataset with the DG-00.03 metrics and Wilson 95% intervals. Arm C on D3 and D1 is the
DG-00.03 run (same model, prompt and settings); arm B is the D16 variant ("BP": the Ossie model
with the caller's physical columns), and DG-00.03's arm B (model only) is shown beside it.
"""

from __future__ import annotations

import json
import pathlib

HERE = pathlib.Path(__file__).parent
# dataset -> [(column label, run, arm id in that run)]
RUNS = {
    "d3": [
        ("C", "full-d3", "C"),
        ("B (D16)", "bp-d3", "BP"),
        ("A1", "ao-d3-a1", "A1"),
        ("A2", "ao-d3-a2", "A2"),
        ("B, model only (DG-00.03)", "full-d3", "B"),
    ],
    "d1": [
        ("C", "full-d1", "C"),
        ("B (D16)", "bp-d1", "BP"),
        ("A1", "ao-d1-a1", "A1"),
        ("A2", "ao-d1-a2", "A2"),
        ("B, model only (DG-00.03)", "full-d1", "B"),
    ],
    "d2": [
        ("C", "cb-d2", "C"),
        ("B (D16)", "cb-d2", "BP"),
        ("A1", "ao-d2-a1", "A1"),
        ("A2", "ao-d2-a2", "A2"),
    ],
}
TITLES = {
    "d3": "D3, the Neuron mart (200 answerable, 60 unanswerable, 40 ambiguous, 34 adversarial; 3 personas)",
    "d1": "D1, Wide World Importers (39 questions, one reader)",
    "d2": "D2, BIRD Mini-Dev PostgreSQL (500 questions, one reader; indicative only)",
}


def pct(x: dict | None) -> str:
    if not x or not x.get("n"):
        return "n/a"
    lo, hi = x["wilson95"]
    return f"{x['k']}/{x['n']} = {100 * x['rate']:.1f}% [{100 * lo:.1f}, {100 * hi:.1f}]"


ROWS = [
    (
        "Execution accuracy, answerable questions (every persona right)",
        lambda s: pct(s["questions"].get("answerable")),
    ),
    ("Execution accuracy, answerable units", lambda s: pct(s["execution_accuracy_units"])),
    ("Accuracy where the engine wrote SQL", lambda s: pct(s["accuracy_when_answered_units"])),
    (
        "Answerable units not answered (refused or clarified)",
        lambda s: pct(s["not_answered_units"]),
    ),
    (
        "Wrong answers without refusal or clarification (units)",
        lambda s: pct(s["wrong_answers_without_refusal"]),
    ),
    ("Correct refusals, unanswerable questions", lambda s: pct(s["questions"].get("unanswerable"))),
    ("Correct refusals, no-access units", lambda s: pct(s["no_access_refused"])),
    ("Correct clarifications, ambiguous questions", lambda s: pct(s["questions"].get("ambiguous"))),
    ("Adversarial questions handled correctly", lambda s: pct(s["questions"].get("adversarial"))),
    (
        "Adversarial units that followed a planted instruction",
        lambda s: pct(s.get("adversarial_followed_planted")),
    ),
    ("Statements the guard rejected (never executed)", lambda s: str(s["guard_rejected"])),
    ("Statements that failed in the database", lambda s: str(s["exec_errors"])),
    ("p95 latency per question (s)", lambda s: str(s["p95_latency_s"])),
    (
        "Model calls",
        lambda s: "not observable" if s["model_calls"] is None else str(s["model_calls"]),
    ),
    ("Units scored", lambda s: str(s["units"])),
]


def main() -> str:
    out = [
        "# DG-00.05 results",
        "",
        "Model in every arm: nvidia/nemotron-3-ultra-550b-a55b (`LLM_MODEL`). Rates with Wilson 95% intervals.",
        "Every SQL answer, from every arm, went through the same guard and the persona's read-only executor.",
        "",
    ]
    for ds, cols in RUNS.items():
        have = []
        for label, run, arm in cols:
            p = HERE / "runs" / run / "score.json"
            if p.exists():
                s = json.loads(p.read_text())["arms"].get(arm)
                if s:
                    have.append((label, s))
        if not have:
            continue
        out += [
            f"## {TITLES[ds]}",
            "",
            "| Measure | " + " | ".join(lbl for lbl, _ in have) + " |",
            "| --- |" + " --- |" * len(have),
        ]
        out += [f"| {name} | " + " | ".join(f(s) for _, s in have) + " |" for name, f in ROWS]
        out.append("")
    return "\n".join(out)


if __name__ == "__main__":
    print(main())
