# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Fail a DAST run on findings of medium risk or above that no rule excuses (ADR 0012, #331).

    python scripts/dast_gate.py zap-report.json deploy/reference/zap-rules.tsv

`zap-report.json` is ZAP's JSON report. The rules file holds one `<pluginid><TAB><reason>` per
line (`#` starts a comment); a listed plugin is ignored, and the reason is required. Prints each
unexcused finding and exits 1 if there is any, 2 on a malformed rules file or report.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

MEDIUM = 2  # ZAP riskcode: 0 info, 1 low, 2 medium, 3 high


def load_rules(text: str) -> dict[str, str]:
    rules: dict[str, str] = {}
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        plugin, _, reason = line.partition("\t")
        if not plugin.strip().isdigit() or not reason.strip():
            raise ValueError(f"rules line {number}: expected '<pluginid><TAB><reason>'")
        rules[plugin.strip()] = reason.strip()
    return rules


def unexcused(report: dict[str, object], rules: dict[str, str]) -> list[str]:
    """`<pluginid> <risk> <name>` for every medium-or-higher alert without a rule."""
    found: list[str] = []
    sites = report.get("site", [])
    if not isinstance(sites, list):
        raise ValueError("report has no site list")
    for site in sites:
        for alert in site.get("alerts", []):
            if int(alert.get("riskcode", 0)) >= MEDIUM and str(alert["pluginid"]) not in rules:
                found.append(f"{alert['pluginid']} {alert.get('riskdesc', '')} {alert['name']}")
    return found


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: dast_gate.py REPORT.json RULES.tsv", file=sys.stderr)
        return 2
    try:
        rules = load_rules(Path(argv[2]).read_text(encoding="utf-8"))
        findings = unexcused(json.loads(Path(argv[1]).read_text(encoding="utf-8")), rules)
    except (OSError, ValueError, KeyError) as exc:
        print(f"dast_gate: {exc}", file=sys.stderr)
        return 2
    for line in findings:
        print(line)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
