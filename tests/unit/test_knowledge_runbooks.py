"""The Knowledge Engine runbooks in OPERATIONS.md (RAG-08.04) name only real error codes."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_RUNBOOKS = (
    "Worker down",
    "Parser down",
    "Embedding provider outage",
    "Re-running a failed document",
)


def _section() -> str:
    text = (ROOT / "OPERATIONS.md").read_text(encoding="utf-8")
    start = text.index("### Knowledge Engine\n")
    return text[start : text.index("\n### ", start + 1)]


def _raised_codes() -> set[str]:
    """Every string literal the knowledge package passes as an error's code or stores."""
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "src" / "neuron_agent" / "knowledge").glob("*.py")
    )
    return set(re.findall(r"""["']([a-z]+(?:_[a-z]+)+)["']""", source))


def test_every_knowledge_runbook_is_present() -> None:
    section = _section()
    for title in _RUNBOOKS:
        assert f"#### {title}\n" in section


def test_runbooks_name_only_codes_the_knowledge_engine_records() -> None:
    section = _section()
    # A table row's first cell, and the codes listed in "Re-running a failed document".
    named = set(re.findall(r"^\| `([a-z_]+)`", section, re.MULTILINE))
    rerun = section[section.index("#### Re-running a failed document") :]
    named |= set(re.findall(r"`([a-z]+(?:_[a-z]+)+)`", rerun.split("\n2. ")[0]))
    named.discard("error_code")
    assert len(named) >= 12
    assert named <= _raised_codes(), sorted(named - _raised_codes())
