# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Token usage per agent and issue from Claude Code session transcripts (#162).

    uv run python scripts/token_report.py <transcript-dir> [-o report.md]

Reads every `*.jsonl` under the directory. A file below a `subagents` directory is one
subagent; any other file is a main (orchestrator) session. Usage is summed per agent from
assistant records, counted once per message id. The Markdown report holds token counts,
agent ids, roles and issue numbers only, never prompt or response text. It reports tokens,
not money. Malformed lines are skipped and counted. Exit code: 0 ok, 2 misuse.

The issue number is the most frequent `#<digits>` in the agent's prompt (the first user
message of a subagent); the role comes from keywords in that prompt. Main sessions have no
single prompt and are listed as unattributed, role other.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

FIELDS = ("input", "output", "cache_read", "cache_write")
_USAGE_KEYS = {
    "input": "input_tokens",
    "output": "output_tokens",
    "cache_read": "cache_read_input_tokens",
    "cache_write": "cache_creation_input_tokens",
}
ROLES = ("implement", "review", "CI fix", "other")
UNATTRIBUTED = "unattributed"
_ISSUE = re.compile(r"(?<![\w&/])#(\d{1,6})\b")
# Checked in order: a CI-fix prompt usually also mentions the implementation or review.
_ROLE_PATTERNS = (
    (
        "CI fix",
        re.compile(
            r"\bci\b[\s-]*(fix|fail|red|re-?push)|\b(fix\w*|repair\w*|failing)\W+(\w+\W+){0,3}ci\b",
            re.I,
        ),
    ),
    ("review", re.compile(r"\breview", re.I)),
    ("implement", re.compile(r"\b(implement|build|add|create|write)\b", re.I)),
)
_TABLE_HEAD = (
    "| {} | Agents | Input | Output | Cache read | Cache write |\n|---|---:|---:|---:|---:|---:|"
)


@dataclass
class AgentUsage:
    agent: str
    issue: str = UNATTRIBUTED
    role: str = "other"
    totals: dict[str, int] = field(default_factory=lambda: dict.fromkeys(FIELDS, 0))


def infer_issue(prompt: str) -> str:
    found = _ISSUE.findall(prompt)
    if not found:
        return UNATTRIBUTED
    counts = Counter(found)
    best = max(counts.values())
    return f"#{next(n for n in found if counts[n] == best)}"


def infer_role(prompt: str) -> str:
    for role, pattern in _ROLE_PATTERNS:
        if pattern.search(prompt):
            return role
    return "other"


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            b["text"] for b in content if isinstance(b, dict) and isinstance(b.get("text"), str)
        )
    return ""


def _usage_counts(usage: Any) -> dict[str, int] | None:
    """The four counts from a usage object, or None when any is missing or not an integer."""
    if not isinstance(usage, dict):
        return None
    counts: dict[str, int] = {}
    for name, key in _USAGE_KEYS.items():
        value = usage.get(key)
        if not isinstance(value, int) or isinstance(value, bool):
            return None
        counts[name] = value
    return counts


def read_agent(path: Path, *, subagent: bool) -> tuple[AgentUsage, int]:
    """Return the agent's usage and the number of malformed lines skipped."""
    agent = AgentUsage(agent=path.stem if subagent else f"main-{path.stem[:8]}")
    seen: set[str] = set()
    prompt: str | None = None
    skipped = 0
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError:
                skipped += 1
                continue
            if not isinstance(record, dict):
                skipped += 1
                continue
            message = record.get("message")
            if not isinstance(message, dict):
                continue
            if record.get("type") == "user" and prompt is None:
                prompt = _text(message.get("content"))
            if record.get("type") != "assistant":
                continue
            counts = _usage_counts(message.get("usage"))
            if counts is None:
                skipped += 1
                continue
            message_id = message.get("id")
            if isinstance(message_id, str):
                if message_id in seen:  # one record per content block repeats the usage
                    continue
                seen.add(message_id)
            for name, value in counts.items():
                agent.totals[name] += value
    if subagent and prompt:
        agent.issue = infer_issue(prompt)
        agent.role = infer_role(prompt)
    return agent, skipped


def collect(root: Path) -> tuple[list[AgentUsage], int, int]:
    """Return (agents, files read, malformed lines skipped)."""
    agents: list[AgentUsage] = []
    skipped = 0
    files = sorted(root.rglob("*.jsonl"))
    for path in files:
        agent, bad = read_agent(path, subagent="subagents" in path.relative_to(root).parts)
        agents.append(agent)
        skipped += bad
    return agents, len(files), skipped


def _sum(items: Iterable[AgentUsage]) -> dict[str, int]:
    total = dict.fromkeys(FIELDS, 0)
    for item in items:
        for name in FIELDS:
            total[name] += item.totals[name]
    return total


def _row(label: str, group: list[AgentUsage]) -> str:
    totals = _sum(group)
    return "| " + " | ".join([label, str(len(group))] + [f"{totals[f]:,}" for f in FIELDS]) + " |"


def _issue_key(issue: str) -> tuple[int, int]:
    return (1, 0) if issue == UNATTRIBUTED else (0, int(issue[1:]))


def render(agents: list[AgentUsage], files: int, skipped: int) -> str:
    issues = sorted({a.issue for a in agents}, key=_issue_key)
    out = [
        "# Token usage report",
        "",
        "Token counts only, not money: no prices or costs are applied. The report holds "
        "counts, agent ids, roles and issue numbers, never prompt or response text.",
        "",
        f"Transcript files read: {files}. Agents: {len(agents)}. "
        f"Malformed lines skipped: {skipped}.",
        "",
        "## Total",
        "",
        _TABLE_HEAD.format("Scope"),
        _row("all agents", agents),
        "",
        "## By issue",
        "",
        _TABLE_HEAD.format("Issue"),
    ]
    out += [_row(i, [a for a in agents if a.issue == i]) for i in issues]
    out += ["", "## By role", "", _TABLE_HEAD.format("Role")]
    out += [_row(r, [a for a in agents if a.role == r]) for r in ROLES]
    out += ["", "## By issue and role", "", _TABLE_HEAD.format("Issue / role")]
    for issue in issues:
        for role in ROLES:
            group = [a for a in agents if a.issue == issue and a.role == role]
            if group:
                out.append(_row(f"{issue} / {role}", group))
    out += [
        "",
        "## Per agent",
        "",
        "| Agent | Issue | Role | Input | Output | Cache read | Cache write |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for a in sorted(agents, key=lambda x: (_issue_key(x.issue), x.role, x.agent)):
        counts = " | ".join(f"{a.totals[f]:,}" for f in FIELDS)
        out.append(f"| {a.agent} | {a.issue} | {a.role} | {counts} |")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Token usage per agent and issue.")
    parser.add_argument("transcript_dir", type=Path)
    parser.add_argument("-o", "--output", type=Path, help="write the report here (default stdout)")
    args = parser.parse_args(argv)
    if not args.transcript_dir.is_dir():
        print("error: transcript directory not found", file=sys.stderr)
        return 2
    agents, files, skipped = collect(args.transcript_dir)
    report = render(agents, files, skipped)
    if args.output:
        args.output.write_text(report, encoding="utf-8")
    else:
        sys.stdout.write(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
