# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Print which user-facing flows have which end-to-end tests.

Tests name the flows they cover: `@pytest.mark.flow("approval", ...)` in Python and
`{ tag: ["@approval"] }` in Playwright. This script collects both and prints a table. It is a
report, not a gate: it always exits 0, so a flow without a test shows as `-` instead of failing
the build. In GitHub Actions it also writes the table to the job summary.

    uv run python scripts/flow_report.py
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess  # noqa: S404 - runs `npx playwright test --list`, a fixed command
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

# The user-facing flows, in the order the table lists them.
FLOWS: dict[str, str] = {
    "auth": "Sign in and out; the API refuses requests without a token",
    "authorization": "A token without the permission is refused",
    "chat": "Send a message, stream the answer",
    "resume": "Reload and continue a conversation",
    "approval": "Approve or reject a remembered note",
    "memories": "List and delete remembered notes",
    "threads": "Rename and delete conversations",
    "feedback": "Rate an answer",
    "data-rights": "Export and erase my data",
    "isolation": "One user cannot see another's data",
    "validation": "Bad requests are rejected before a run starts",
    "security": "Hostile text, third-party origins, tokens in storage",
    "theme": "Light, dark and system colour scheme",
}


def python_flows(tests_dir: Path) -> dict[str, list[str]]:
    """Map flow name to the Python tests marked with `pytest.mark.flow(...)`."""
    found: dict[str, list[str]] = {}
    for path in sorted(tests_dir.rglob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for decorator in node.decorator_list:
                if (
                    isinstance(decorator, ast.Call)
                    and ast.unparse(decorator.func) == "pytest.mark.flow"
                ):
                    for arg in decorator.args:
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            found.setdefault(arg.value, []).append(node.name)
    return found


def _walk(suite: dict[str, Any], found: dict[str, list[str]]) -> None:
    for spec in suite.get("specs", []):
        for tag in spec.get("tags", []):
            found.setdefault(str(tag).lstrip("@"), []).append(str(spec["title"]))
    for child in suite.get("suites", []):
        _walk(child, found)


def browser_flows(web_dir: Path) -> dict[str, list[str]] | None:
    """Map flow name to the Playwright tests tagged with it, or None if they can't be listed."""
    npx = shutil.which("npx")
    if npx is None:
        return None
    try:
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [npx, "playwright", "test", "--list", "--reporter=json"],
            cwd=web_dir,
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        )
        report = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return None
    found: dict[str, list[str]] = {}
    for suite in report.get("suites", []):
        _walk(suite, found)
    return found


def render(api: dict[str, list[str]], browser: dict[str, list[str]] | None) -> str:
    rows = [
        "| Flow | What | API e2e | Browser e2e |",
        "| --- | --- | ---: | ---: |",
    ]
    unknown = sorted((set(api) | set(browser or {})) - set(FLOWS))
    for name, what in [*FLOWS.items(), *((n, "(not in FLOWS)") for n in unknown)]:
        browser_cell = "n/a" if browser is None else str(len(browser.get(name, [])) or "-")
        rows.append(f"| {name} | {what} | {len(api.get(name, [])) or '-'} | {browser_cell} |")
    missing = [n for n in FLOWS if not api.get(n) and not (browser or {}).get(n)]
    rows.append("")
    rows.append("Flows with no end-to-end test: " + (", ".join(missing) or "none") + ".")
    if browser is None:
        rows.append("Browser tests could not be listed (is `npx playwright` available in web/?).")
    return "\n".join(rows)


def main() -> int:
    table = render(python_flows(ROOT / "tests"), browser_flows(ROOT / "web"))
    print(table)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("## Flow coverage\n\n" + table + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
