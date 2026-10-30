# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Fail unless a pytest JUnit report shows executed Postgres tests (#142).

A skipped test exits 0, and an unset `APP_TEST_POSTGRES_DSN` skips every Postgres test,
so the exit code alone cannot prove the tests ran.

    uv run python scripts/require_postgres_tests.py postgres-junit.xml
"""

from __future__ import annotations

import sys
from pathlib import Path
from xml.etree import ElementTree  # noqa: S405 - parses our own pytest output


def check(path: Path) -> str | None:
    """Return a failure message, or None when tests ran and none were skipped."""
    root = ElementTree.parse(path).getroot()  # noqa: S314
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    total = sum(int(s.get("tests", 0)) for s in suites)
    skipped = sum(int(s.get("skipped", 0)) for s in suites)
    print(f"postgres tests: selected={total} skipped={skipped}")
    if total == 0:
        return "No Postgres tests were selected."
    if skipped:
        return f"{skipped} Postgres test(s) were skipped (is APP_TEST_POSTGRES_DSN set?)."
    return None


def main(argv: list[str]) -> int:
    failure = check(Path(argv[1]))
    if failure:
        print(failure, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
