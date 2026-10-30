# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Print one version's section of CHANGELOG.md (for release notes).

Usage: python scripts/changelog_section.py 0.5.0 [CHANGELOG.md]

Exits 1 when the changelog has no non-empty section for that version.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


def extract_section(text: str, version: str) -> str | None:
    """Return the body under `## <version>` up to the next `## ` heading, or None."""
    lines = text.splitlines()
    heading = re.compile(rf"^##\s+v?{re.escape(version)}\s*$")
    for start, line in enumerate(lines):
        if heading.match(line):
            body: list[str] = []
            for following in lines[start + 1 :]:
                if following.startswith("## "):
                    break
                body.append(following)
            section = "\n".join(body).strip()
            return section or None
    return None


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3):
        print("usage: changelog_section.py VERSION [CHANGELOG.md]", file=sys.stderr)
        return 2
    path = Path(argv[2]) if len(argv) == 3 else Path(__file__).parents[1] / "CHANGELOG.md"
    section = extract_section(path.read_text(encoding="utf-8"), argv[1])
    if section is None:
        print(f"no CHANGELOG section for version {argv[1]}", file=sys.stderr)
        return 1
    print(section)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
