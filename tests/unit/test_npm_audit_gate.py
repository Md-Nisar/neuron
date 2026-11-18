"""The npm audit gate: advisories fail CI unless ignored with a reason and a near review date."""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any

import yaml
from scripts import npm_audit_gate as gate

TODAY = datetime.date(2026, 11, 18)
GHSA = "GHSA-fc5q-39xc-vjpf"


def _report(*ids: str) -> dict[str, Any]:
    vulns: dict[str, Any] = {
        f"pkg{i}": {"via": [{"name": f"pkg{i}", "url": f"https://github.com/advisories/{ghsa}"}]}
        for i, ghsa in enumerate(ids)
    }
    vulns["dependent"] = {"via": ["pkg0"]}  # a dependent names the package, not an advisory
    return {"auditReportVersion": 2, "vulnerabilities": vulns}


def _entry(**changes: Any) -> dict[str, Any]:
    return {"id": GHSA, "statement": "not reachable", "expired_at": "2027-02-15", **changes}


def test_an_unignored_advisory_fails() -> None:
    assert gate.gate(_report(GHSA), [], TODAY) == [
        f"pkg0: {GHSA} is not fixed and not ignored (or its entry expired)"
    ]


def test_an_ignored_advisory_passes_but_another_one_still_fails() -> None:
    assert gate.gate(_report(GHSA), [_entry()], TODAY) == []
    assert len(gate.gate(_report(GHSA, "GHSA-xxxx-yyyy-zzzz"), [_entry()], TODAY)) == 1


def test_a_clean_report_passes_and_a_failed_audit_does_not() -> None:
    assert gate.gate({"auditReportVersion": 2, "vulnerabilities": {}}, [], TODAY) == []
    assert gate.gate({"error": {"code": "ENOLOCK"}}, [], TODAY)
    assert gate.gate({}, [], TODAY)


def test_an_expired_entry_ignores_nothing() -> None:
    expired = _entry(expired_at="2026-11-17")
    assert gate.gate(_report(GHSA), [expired], TODAY)
    assert gate.gate(_report(GHSA), [_entry(expired_at="2026-11-18")], TODAY) == []


def test_entries_need_an_id_a_reason_and_a_date_within_90_days() -> None:
    assert gate.ignore_problems([_entry(expired_at="2027-02-16")], TODAY) == []
    assert gate.ignore_problems([_entry(expired_at="2027-02-17")], TODAY)
    assert gate.ignore_problems([_entry(statement=" ")], TODAY)
    assert gate.ignore_problems([_entry(id="")], TODAY)
    assert gate.ignore_problems([_entry(expired_at="soon")], TODAY)
    assert gate.ignore_problems([{"id": GHSA, "statement": "x"}], TODAY)
    # An entry without a reason ignores nothing, even before its date.
    assert gate.gate(_report(GHSA), [_entry(statement="")], TODAY)


def test_the_ignore_file_follows_the_rule_today_and_is_listed_in_security_md() -> None:
    entries = json.loads(Path(".npm-audit-ignore.json").read_text("utf-8"))["advisories"]
    assert gate.ignore_problems(entries, datetime.date.today()) == []
    security = Path("SECURITY.md").read_text("utf-8")
    for entry in entries:
        assert entry["id"] in security


def test_ci_runs_the_gate_for_both_npm_packages() -> None:
    jobs = yaml.safe_load(Path(".github/workflows/ci.yml").read_text("utf-8"))["jobs"]
    for name in ("web", "keycloak-theme"):
        runs = [step["run"] for step in jobs[name]["steps"] if "run" in step]
        assert "python3 ../scripts/npm_audit_gate.py ." in runs, name
        assert not [run for run in runs if run.startswith("npm audit")], name
