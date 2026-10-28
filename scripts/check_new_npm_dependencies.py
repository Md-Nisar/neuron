# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Verify npm packages a pull request adds to `web/package.json` (AI code verification gate).

The npm twin of `check_new_dependencies.py`: for every package newly named in `dependencies`,
`devDependencies`, `optionalDependencies` or `peerDependencies`, confirm on the npm registry
that it exists and that its first publication is at least MIN_AGE_DAYS old ("slopsquatting").
A package that passes still needs a reviewer to confirm it is the intended project.

Usage: python scripts/check_new_npm_dependencies.py <base-package.json> <head-package.json>

A base file that does not exist counts as an empty manifest (the PR that creates `web/`).
Exit codes: 0 no new packages or all checks passed, 1 a check failed, 2 registry unreachable.
Set ALLOW_YOUNG_PACKAGES=true (the `new-dependency-approved` PR label) to accept young packages.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MIN_AGE_DAYS = 90
REGISTRY_URL = "https://registry.npmjs.org/{name}"
_NAME = re.compile(r"^(@[a-z0-9~-][a-z0-9._~-]*/)?[a-z0-9~-][a-z0-9._~-]*$")
_SECTIONS = ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies")


def declared_packages(manifest: dict[str, Any]) -> set[str]:
    """Every package named in the manifest's dependency sections."""
    names: set[str] = set()
    for section in _SECTIONS:
        entries = manifest.get(section, {})
        if isinstance(entries, dict):
            names.update(name for name in entries if isinstance(name, str))
    return names


@dataclass(frozen=True)
class Verdict:
    name: str
    ok: bool
    message: str


def judge(name: str, metadata: dict[str, Any] | None, now: datetime, allow_young: bool) -> Verdict:
    """Decide whether a newly added package may pass, from its registry document."""
    if metadata is None:
        return Verdict(name, False, "not found on the npm registry - possibly a hallucinated name")
    created = metadata.get("time", {}).get("created")
    if not isinstance(created, str):
        return Verdict(name, False, "registry document has no creation time")
    age_days = (now - datetime.fromisoformat(created.replace("Z", "+00:00"))).days
    releases = len(metadata.get("versions", {}))
    detail = f"first published {age_days} days ago, {releases} versions"
    if age_days < MIN_AGE_DAYS and not allow_young:
        return Verdict(name, False, f"younger than {MIN_AGE_DAYS} days ({detail})")
    return Verdict(name, True, detail)


def fetch_metadata(name: str) -> dict[str, Any] | None:
    """The registry document for `name`, or None if the registry has no such package."""
    if not _NAME.fullmatch(name):
        raise ValueError(f"not a valid npm package name: {name!r}")
    url = REGISTRY_URL.format(name=urllib.parse.quote(name, safe="@"))  # fixed https host
    request = urllib.request.Request(url, headers={"User-Agent": "neuron-dependency-check"})  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310  # nosec B310
            data: dict[str, Any] = json.load(response)
            return data
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise


def _load(path: str) -> dict[str, Any]:
    file = Path(path)
    if not file.exists():
        return {}
    loaded: dict[str, Any] = json.loads(file.read_text(encoding="utf-8"))
    return loaded


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    added = sorted(declared_packages(_load(argv[2])) - declared_packages(_load(argv[1])))
    if not added:
        print("No new npm dependencies.")
        return 0
    allow_young = os.environ.get("ALLOW_YOUNG_PACKAGES", "").lower() == "true"
    now = datetime.now(UTC)
    failed = False
    for name in added:
        try:
            verdict = judge(name, fetch_metadata(name), now, allow_young)
        except (urllib.error.URLError, TimeoutError) as error:
            print(f"::error::Could not reach the npm registry to check {name}: {error}")
            return 2
        level = "notice" if verdict.ok else "error"
        print(f"::{level}::New npm dependency {verdict.name}: {verdict.message}")
        failed = failed or not verdict.ok
    print("A reviewer must confirm each new dependency is the intended, reputable project.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
