"""The token usage report (`scripts/token_report.py`, #162), on a synthetic transcript."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts import token_report

MARKER = "sk-MARKER-do-not-leak"


def _assistant(msg_id: str, i: int, o: int, cr: int, cw: int) -> dict[str, Any]:
    return {
        "type": "assistant",
        "message": {
            "id": msg_id,
            "content": [{"type": "text", "text": f"reply {MARKER}"}],
            "usage": {
                "input_tokens": i,
                "output_tokens": o,
                "cache_read_input_tokens": cr,
                "cache_creation_input_tokens": cw,
            },
        },
    }


def _user(text: str) -> dict[str, Any]:
    return {"type": "user", "message": {"role": "user", "content": text}}


def _write(path: Path, records: list[Any], extra: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n" + extra, encoding="utf-8")


def _fixture(root: Path) -> None:
    _write(
        root / "abcdef123456.jsonl",
        [_user(f"orchestrate #1 {MARKER}"), _assistant("m0", 1, 2, 3, 4)],
    )
    sub = root / "abcdef123456" / "subagents"
    _write(
        sub / "agent-a1.jsonl",
        [
            _user(f"Implement GitHub issue #162 and mention #7 once. {MARKER}"),
            _assistant("m1", 10, 20, 30, 40),
            _assistant("m1", 10, 20, 30, 40),  # repeated block of the same message
            _assistant("m2", 1, 1, 1, 1),
        ],
        extra="not json\n[1]\n",
    )
    _write(sub / "agent-a2.jsonl", [_user("Review the PR for #162"), _assistant("m3", 5, 5, 5, 5)])
    _write(
        sub / "agent-a3.jsonl", [_user("Fix the failing CI on #162"), _assistant("m4", 2, 2, 2, 2)]
    )
    _write(sub / "agent-a4.jsonl", [_user("Look around the repo"), _assistant("m5", 3, 3, 3, 3)])


def test_totals_grouping_and_malformed_lines(tmp_path: Path) -> None:
    _fixture(tmp_path)
    agents, files, skipped = token_report.collect(tmp_path)
    by_name = {a.agent: a for a in agents}
    assert files == 5
    assert skipped == 2
    assert by_name["agent-a1"].totals == {
        "input": 11,
        "output": 21,
        "cache_read": 31,
        "cache_write": 41,
    }
    assert (by_name["agent-a1"].issue, by_name["agent-a1"].role) == ("#162", "implement")
    assert by_name["agent-a2"].role == "review"
    assert by_name["agent-a3"].role == "CI fix"
    assert (by_name["agent-a4"].issue, by_name["agent-a4"].role) == ("unattributed", "other")
    assert by_name["main-abcdef12"].issue == "unattributed"


def test_report_has_counts_only(tmp_path: Path) -> None:
    _fixture(tmp_path)
    out = tmp_path / "report.md"
    assert token_report.main([str(tmp_path), "-o", str(out)]) == 0
    report = out.read_text(encoding="utf-8")
    assert MARKER not in report
    assert "reply" not in report and "Look around" not in report
    assert "not money" in report
    assert "Malformed lines skipped: 2" in report
    assert "| #162 | 3 |" in report
    assert report.index("#162") < report.index("unattributed")


def test_missing_directory_is_misuse(tmp_path: Path) -> None:
    assert token_report.main([str(tmp_path / "nope")]) == 2
