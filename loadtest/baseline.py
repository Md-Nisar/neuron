# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Turn step files into a load baseline and compare a later run with it (ADR 0012).

    python -m loadtest.baseline build --steps DIR --out FILE --image ID --profile TEXT
    python -m loadtest.baseline compare BASELINE.json NEW.json

`DIR` holds one `<scenario>.jsonl` per scenario (the files `loadtest.shape` writes). Numbers are
for the machine named in the file only; `compare` refuses a run from another host or profile.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from pathlib import Path
from typing import Any

REGRESSION_LIMIT = 0.10


def _load_steps(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def scenario_result(steps: list[dict[str, Any]]) -> dict[str, Any]:
    """The highest rate inside the SLOs, the step it came from, and what broke next."""
    ok = [s for s in steps if not s["breaches"]]

    def rate(step: dict[str, Any]) -> float:
        return float(step["runs"]) / float(step["seconds"])

    best = max(ok, key=rate) if ok else None
    broken = next((s for s in steps if s["breaches"]), None)
    return {
        "sustained_runs_per_second": round(rate(best), 2) if best else 0.0,
        "knee_users": best["users"] if best else 0,
        "steps": len(steps),
        "slo_broken": broken is not None,
        "first_breach": (
            {"users": broken["users"], "breaches": broken["breaches"], "errors": broken["errors"]}
            if broken
            else None
        ),
        "ttft_p90_ms_at_knee": best["ttft_p90_ms"] if best else None,
        "run_p95_ms_at_knee": best["run_p95_ms"] if best else None,
    }


def host_description() -> str:
    return f"{platform.system()} {platform.machine()}, {os.cpu_count()} CPUs"


def build(
    steps_dir: Path, image: str, profile: str, note: str, host: str | None = None
) -> dict[str, Any]:
    return {
        "image": image,
        "host": host or host_description(),
        "fake_model_profile": profile,
        "note": note,
        "scenarios": {
            path.stem: scenario_result(_load_steps(path))
            for path in sorted(steps_dir.glob("*.jsonl"))
        },
    }


def compare(baseline: dict[str, Any], new: dict[str, Any]) -> list[str]:
    """Regressions of more than 10% in sustained runs per second; raises on a host mismatch."""
    for key in ("host", "fake_model_profile"):
        if baseline[key] != new[key]:
            raise ValueError(f"{key} differs: baseline {baseline[key]!r}, new {new[key]!r}")
    found = []
    for name, old in baseline["scenarios"].items():
        current = new["scenarios"].get(name)
        if current is None:
            found.append(f"{name}: missing from the new run")
            continue
        before = old["sustained_runs_per_second"]
        after = current["sustained_runs_per_second"]
        if before > 0 and (before - after) / before > REGRESSION_LIMIT:
            found.append(f"{name}: {before} -> {after} runs/s (more than 10% lower)")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="loadtest.baseline")
    commands = parser.add_subparsers(dest="command", required=True)
    build_parser = commands.add_parser("build")
    build_parser.add_argument("--steps", type=Path, required=True)
    build_parser.add_argument("--out", type=Path, required=True)
    build_parser.add_argument("--image", required=True)
    build_parser.add_argument("--profile", required=True)
    build_parser.add_argument("--note", default="")
    compare_parser = commands.add_parser("compare")
    compare_parser.add_argument("baseline", type=Path)
    compare_parser.add_argument("new", type=Path)
    args = parser.parse_args(argv)
    if args.command == "build":
        document = build(args.steps, args.image, args.profile, args.note)
        args.out.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        return 0
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    new = json.loads(args.new.read_text(encoding="utf-8"))
    try:
        regressions = compare(baseline, new)
    except ValueError as exc:
        print(f"not comparable: {exc}", file=sys.stderr)
        return 2
    for line in regressions:
        print(line)
    return 1 if regressions else 0


if __name__ == "__main__":
    raise SystemExit(main())
