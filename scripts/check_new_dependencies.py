"""Verify dependencies a pull request adds to `pyproject.toml` (AI code verification gate).

AI assistants recommend packages that do not exist about 5-20% of the time, and attackers
register those names ("slopsquatting"). This check compares the declared dependencies of the
PR head with the base branch and, for every newly added package, confirms on PyPI that it
exists and is not brand new. It is a gate for humans, not a substitute for review: a package
that passes still needs a reviewer to confirm it is the intended, reputable project.

Usage: python scripts/check_new_dependencies.py <base-pyproject.toml> <head-pyproject.toml>

Exit codes: 0 no new packages or all checks passed, 1 a check failed, 2 PyPI unreachable.
Set ALLOW_YOUNG_PACKAGES=true (the `new-dependency-approved` PR label) to accept packages
whose first release is younger than MIN_AGE_DAYS after a human has vetted them.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MIN_AGE_DAYS = 90
PYPI_URL = "https://pypi.org/pypi/{name}/json"
_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def normalize(name: str) -> str:
    """PEP 503 normalized project name."""
    return re.sub(r"[-_.]+", "-", name).lower()


def requirement_name(requirement: str) -> str | None:
    """Project name of a PEP 508 requirement string, or None if it has none."""
    match = _NAME.match(requirement)
    return normalize(match.group(1)) if match else None


def declared_packages(pyproject: dict[str, Any]) -> set[str]:
    """Every package named in project, optional and dependency-group requirements."""
    project = pyproject.get("project", {})
    requirements: list[str] = list(project.get("dependencies", []))
    for extra in project.get("optional-dependencies", {}).values():
        requirements.extend(extra)
    for group in pyproject.get("dependency-groups", {}).values():
        requirements.extend(item for item in group if isinstance(item, str))
    own_name = normalize(project["name"]) if "name" in project else None
    names = {requirement_name(item) for item in requirements}
    return {name for name in names if name and name != own_name}


@dataclass(frozen=True)
class Verdict:
    name: str
    ok: bool
    message: str


def judge(name: str, metadata: dict[str, Any] | None, now: datetime, allow_young: bool) -> Verdict:
    """Decide whether a newly added package may pass, from its PyPI JSON metadata."""
    if metadata is None:
        return Verdict(name, False, "not found on PyPI - possibly a hallucinated package name")
    uploads = [
        datetime.fromisoformat(file["upload_time_iso_8601"].replace("Z", "+00:00"))
        for files in metadata.get("releases", {}).values()
        for file in files
        if file.get("upload_time_iso_8601")
    ]
    if not uploads:
        return Verdict(name, False, "exists on PyPI but has no uploaded files")
    age_days = (now - min(uploads)).days
    releases = len(metadata.get("releases", {}))
    summary = metadata.get("info", {}).get("summary") or "no summary"
    detail = f"first release {age_days} days ago, {releases} releases: {summary}"
    if age_days < MIN_AGE_DAYS and not allow_young:
        return Verdict(name, False, f"younger than {MIN_AGE_DAYS} days ({detail})")
    return Verdict(name, True, detail)


def fetch_metadata(name: str) -> dict[str, Any] | None:
    """PyPI JSON metadata for `name`, or None if PyPI has no such project."""
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name):
        raise ValueError(f"not a normalized project name: {name!r}")
    url = PYPI_URL.format(name=name)  # fixed https host, validated name
    request = urllib.request.Request(url, headers={"User-Agent": "neuron-dependency-check"})  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310  # nosec B310
            data: dict[str, Any] = json.load(response)
            return data
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    base = declared_packages(tomllib.loads(Path(argv[1]).read_text(encoding="utf-8")))
    head = declared_packages(tomllib.loads(Path(argv[2]).read_text(encoding="utf-8")))
    added = sorted(head - base)
    if not added:
        print("No new dependencies.")
        return 0
    allow_young = os.environ.get("ALLOW_YOUNG_PACKAGES", "").lower() == "true"
    now = datetime.now(UTC)
    failed = False
    for name in added:
        try:
            verdict = judge(name, fetch_metadata(name), now, allow_young)
        except (urllib.error.URLError, TimeoutError) as error:
            print(f"::error::Could not reach PyPI to check {name}: {error}")
            return 2
        level = "notice" if verdict.ok else "error"
        print(f"::{level}::New dependency {verdict.name}: {verdict.message}")
        failed = failed or not verdict.ok
    print("A reviewer must confirm each new dependency is the intended, reputable project.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
