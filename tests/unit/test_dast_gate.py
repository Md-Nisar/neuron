"""The DAST gate (scripts/dast_gate.py, #331) and its workflow. No network."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from scripts import dast_gate

_ROOT = Path(__file__).resolve().parents[2]


def _report(*alerts: tuple[str, int]) -> dict[str, object]:
    return {
        "site": [
            {
                "alerts": [
                    {"pluginid": pid, "riskcode": str(risk), "name": f"rule {pid}", "riskdesc": "x"}
                    for pid, risk in alerts
                ]
            }
        ]
    }


def test_medium_and_high_alerts_fail_and_low_and_info_do_not() -> None:
    found = dast_gate.unexcused(_report(("1", 0), ("2", 1), ("3", 2), ("4", 3)), {})
    assert [line.split()[0] for line in found] == ["3", "4"]


def test_a_rule_with_a_reason_excuses_its_plugin_only() -> None:
    rules = dast_gate.load_rules("# comment\n\n3\tstatic docs page, accepted\n")
    found = dast_gate.unexcused(_report(("3", 2), ("4", 3)), rules)
    assert [line.split()[0] for line in found] == ["4"]


@pytest.mark.parametrize("text", ["3\n", "3\t \n", "abc\treason\n"])
def test_a_rule_without_a_reason_or_id_is_refused(text: str) -> None:
    with pytest.raises(ValueError, match="expected"):
        dast_gate.load_rules(text)


def test_main_exit_codes(tmp_path: Path) -> None:
    rules = tmp_path / "rules.tsv"
    rules.write_text("3\tok\n", encoding="utf-8")
    clean, dirty = tmp_path / "clean.json", tmp_path / "dirty.json"
    clean.write_text(json.dumps(_report(("3", 2))), encoding="utf-8")
    dirty.write_text(json.dumps(_report(("9", 3))), encoding="utf-8")
    assert dast_gate.main(["g", str(clean), str(rules)]) == 0
    assert dast_gate.main(["g", str(dirty), str(rules)]) == 1
    assert dast_gate.main(["g", str(tmp_path / "missing.json"), str(rules)]) == 2
    assert dast_gate.main(["g"]) == 2


def test_the_committed_rules_file_is_valid() -> None:
    dast_gate.load_rules((_ROOT / "deploy/reference/zap-rules.tsv").read_text(encoding="utf-8"))


def test_the_workflow_is_manual_read_only_and_pins_the_scanner_by_digest() -> None:
    workflow = yaml.safe_load((_ROOT / ".github/workflows/dast.yml").read_text(encoding="utf-8"))
    assert workflow[True] == {"workflow_dispatch": None}
    assert workflow["permissions"] == {"contents": "read"}
    script = (_ROOT / "scripts/dast_scan.sh").read_text(encoding="utf-8")
    assert "ghcr.io/zaproxy/zaproxy@sha256:" in script
    assert "/openapi.json" in script
