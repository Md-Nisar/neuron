"""AI review layer (`scripts/ai_review.py`): diff parsing, reply parsing, comment placement."""

from __future__ import annotations

import pytest
from scripts import ai_review

DIFF = """diff --git a/src/app.py b/src/app.py
index 1111111..2222222 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1,4 +1,5 @@
 import os
-x = 1
+x = 2
+y = eval(input())
 def f():
     return x
diff --git a/old.txt b/old.txt
deleted file mode 100644
--- a/old.txt
+++ /dev/null
@@ -1 +0,0 @@
-gone
"""


def test_added_lines_tracks_new_file_line_numbers() -> None:
    assert ai_review.added_lines(DIFF) == {"src/app.py": {2, 3}}


def test_extract_json_ignores_thinking_and_prose() -> None:
    reply = (
        '<think>{"not": "this"}</think>Here you go:\n'
        '```json\n{"summary": "ok", "findings": []}\n```'
    )

    assert ai_review.extract_json(reply) == {"summary": "ok", "findings": []}


def test_extract_json_without_object_raises() -> None:
    with pytest.raises(ValueError):
        ai_review.extract_json("no json here")


def test_parse_findings_drops_malformed_and_sorts_by_severity() -> None:
    data = {
        "findings": [
            {"file": "b/src/app.py", "line": "3", "severity": "low", "title": "minor"},
            {"file": "src/app.py", "line": 3, "severity": "CRITICAL", "title": "eval"},
            {"file": "src/app.py", "title": "no line"},
            "not a dict",
            {"file": "src/app.py", "line": 2, "severity": "weird", "title": "unknown sev"},
        ]
    }

    findings = ai_review.parse_findings(data)

    assert [(f.title, f.severity) for f in findings] == [
        ("eval", "critical"),
        ("unknown sev", "medium"),
        ("minor", "low"),
    ]
    assert findings[0].file == "src/app.py"


def test_split_inline_only_anchors_changed_lines() -> None:
    changed = ai_review.added_lines(DIFF)
    on_change = ai_review.Finding("src/app.py", 3, "high", "eval", "why", "fix")
    off_change = ai_review.Finding("src/app.py", 5, "low", "context", "why", "fix")

    inline, general = ai_review.split_inline([on_change, off_change], changed)

    assert inline == [on_change]
    assert general == [off_change]


def test_posted_text_cannot_mention_people() -> None:
    finding = ai_review.Finding("a.py", 1, "low", "ping @org/team", "see @someone", "x")

    assert "@org" not in finding.body()
    assert "@someone" not in ai_review.review_body("by @bot", "m", [finding], 0)
