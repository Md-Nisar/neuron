# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Fail on any npm advisory in a package directory unless it is ignored with a reason.

`npm audit` has no way to ignore one advisory, so this runs `npm audit --json` and checks every
advisory it reports against `.npm-audit-ignore.json` (SECURITY.md, "Dependency
Vulnerabilities"). Each entry needs `id` (the GHSA ID), a `statement` (why it does not apply)
and `expired_at` (YYYY-MM-DD), no more than 90 days after the check. An expired entry no longer
ignores anything, so the gate fails again on that date and the entry must be re-reviewed.

Usage: python scripts/npm_audit_gate.py <package-dir>
Exit codes: 0 no unignored advisory, 1 an advisory or an ignore entry needs attention.
"""

from __future__ import annotations

import datetime
import json
import subprocess  # nosec B404
import sys
from pathlib import Path
from typing import Any

IGNORE_FILE = Path(__file__).resolve().parent.parent / ".npm-audit-ignore.json"
MAX_IGNORE_DAYS = 90


def advisories(report: dict[str, Any]) -> dict[str, str]:
    """GHSA ID -> package, for every advisory in an `npm audit --json` report."""
    found = {}
    for package in report.get("vulnerabilities", {}).values():
        for via in package.get("via", []):
            if isinstance(via, dict):  # a string names a vulnerable dependency, not an advisory
                found[str(via["url"]).rsplit("/", 1)[-1]] = str(via["name"])
    return found


def ignore_problems(entries: list[dict[str, Any]], today: datetime.date) -> list[str]:
    problems = []
    for entry in entries:
        name = str(entry.get("id") or "<no id>")
        if not entry.get("id"):
            problems.append(f"{name}: id is missing")
        if not str(entry.get("statement", "")).strip():
            problems.append(f"{name}: statement (the reason) is missing")
        try:
            expires = datetime.date.fromisoformat(str(entry["expired_at"]))
        except (KeyError, ValueError):
            problems.append(f"{name}: expired_at is missing or not a YYYY-MM-DD date")
            continue
        if expires > today + datetime.timedelta(days=MAX_IGNORE_DAYS):
            problems.append(f"{name}: expired_at is more than {MAX_IGNORE_DAYS} days out")
    return problems


def gate(report: dict[str, Any], entries: list[dict[str, Any]], today: datetime.date) -> list[str]:
    problems = ignore_problems(entries, today)
    ignored = {
        str(e["id"])
        for e in entries
        if str(e.get("expired_at", "")) >= today.isoformat() and e.get("statement")
    }
    for ghsa, package in sorted(advisories(report).items()):
        if ghsa not in ignored:
            problems.append(
                f"{package}: {ghsa} is not fixed and not ignored (or its entry expired)"
            )
    if "vulnerabilities" not in report:  # npm could not audit (registry error, no lockfile)
        problems.append(f"npm audit failed: {report.get('error', 'no report')}")
    return problems


def main(argv: list[str]) -> int:
    # Runs only the fixed `npm audit --json` command, no shell.
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 1
    result = subprocess.run(  # nosec B603 B607
        ["npm", "audit", "--json"], cwd=argv[1], capture_output=True, text=True, check=False
    )
    report = json.loads(result.stdout or "{}")
    entries = json.loads(IGNORE_FILE.read_text("utf-8"))["advisories"]
    problems = gate(report, entries, datetime.date.today())
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        return 1
    print(f"npm audit: no unignored advisory ({len(advisories(report))} ignored)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
