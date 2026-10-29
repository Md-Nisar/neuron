# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""CPU, memory and Postgres connections during a load run, per step (ADR 0012, #340).

    python -m loadtest.resources sample --out samples.jsonl [--interval 5]   # until interrupted
    python -m loadtest.resources summarise --samples samples.jsonl --steps new_thread.jsonl

`sample` polls `docker stats` for every running container and, when a Postgres container is
there, `pg_stat_activity`; it also records the host's CPU use (the load generator shares the
host). `summarise` prints, for each step in a step file, the mean and peak of each series inside
that step's window, so the resource that saturates first is visible next to the SLO breach.
"""

from __future__ import annotations

import argparse
import json
import subprocess  # nosec B404  # fixed docker CLI calls, no shell
import sys
import time
from pathlib import Path
from typing import Any

_UNITS = {"B": 1, "KiB": 1024, "MiB": 1024**2, "GiB": 1024**3}


def parse_percent(text: str) -> float:
    return float(text.strip().rstrip("%") or 0.0)


def parse_bytes(text: str) -> float:
    """`123.4MiB / 15.7GiB` -> bytes of the first figure."""
    used = text.split("/")[0].strip()
    for unit in sorted(_UNITS, key=len, reverse=True):
        if used.endswith(unit):
            return float(used[: -len(unit)]) * _UNITS[unit]
    return float(used)


def host_cpu_percent(before: list[int], after: list[int]) -> float:
    """Busy share between two `/proc/stat` cpu lines (user nice system idle iowait ...)."""
    total = sum(after) - sum(before)
    idle = (after[3] + after[4]) - (before[3] + before[4])
    return 100.0 * (total - idle) / total if total > 0 else 0.0


def _cpu_times() -> list[int]:
    first = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0]
    return [int(value) for value in first.split()[1:]]


def _docker(*args: str) -> str:
    done = subprocess.run(  # noqa: S603  # nosec B603 B607  (fixed docker CLI call)
        ["docker", *args],  # noqa: S607
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return done.stdout


def take_sample(before: list[int]) -> tuple[dict[str, Any], list[int]]:
    now = _cpu_times()
    sample: dict[str, Any] = {"at": time.time(), "host_cpu": host_cpu_percent(before, now)}
    containers: dict[str, dict[str, float]] = {}
    for line in _docker("stats", "--no-stream", "--format", "{{json .}}").splitlines():
        row = json.loads(line)
        containers[row["Name"]] = {
            "cpu": parse_percent(row["CPUPerc"]),
            "mem": parse_bytes(row["MemUsage"]),
        }
    sample["containers"] = containers
    postgres = next((name for name in containers if "postgres" in name), None)
    if postgres:
        query = (
            "select count(*), count(*) filter (where state = 'active') "
            "from pg_stat_activity where datname = 'neuron'"
        )
        out = _docker("exec", postgres, "psql", "-U", "neuron_owner", "-d", "neuron", "-Atc", query)
        if out.strip():
            total, active = out.strip().split("|")
            sample["pg_connections"] = int(total)
            sample["pg_active"] = int(active)
    return sample, now


def summarise_steps(
    samples: list[dict[str, Any]], steps: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """For each step, mean and peak of every series among the samples inside its window."""
    result = []
    for step in steps:
        end = float(step["ended_at"])
        inside = [s for s in samples if end - float(step["seconds"]) <= s["at"] <= end]
        series: dict[str, list[float]] = {}
        for sample in inside:
            series.setdefault("host_cpu", []).append(sample["host_cpu"])
            for key in ("pg_connections", "pg_active"):
                if key in sample:
                    series.setdefault(key, []).append(float(sample[key]))
            for name, values in sample["containers"].items():
                short = name.removeprefix("neuron-").removesuffix("-1")
                series.setdefault(f"{short}.cpu", []).append(values["cpu"])
                series.setdefault(f"{short}.mem_mib", []).append(values["mem"] / 1024**2)
        result.append(
            {
                "users": step["users"],
                "samples": len(inside),
                "series": {
                    key: {"mean": round(sum(v) / len(v), 1), "max": round(max(v), 1)}
                    for key, v in sorted(series.items())
                },
            }
        )
    return result


def _read_lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("sample")
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--interval", type=float, default=5.0)
    fold = sub.add_parser("summarise")
    fold.add_argument("--samples", type=Path, required=True)
    fold.add_argument("--steps", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "summarise":
        folded = summarise_steps(_read_lines(args.samples), _read_lines(args.steps))
        json.dump(folded, sys.stdout, indent=1)
        sys.stdout.write("\n")
        return 0
    before = _cpu_times()
    try:
        with args.out.open("a", encoding="utf-8") as out:
            while True:
                started = time.monotonic()
                sample, before = take_sample(before)
                out.write(json.dumps(sample) + "\n")
                out.flush()
                time.sleep(max(0.0, args.interval - (time.monotonic() - started)))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
