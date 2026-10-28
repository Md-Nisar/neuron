# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Verify npm packages a pull request adds to `web/` (AI code verification gate).

The npm twin of `check_new_dependencies.py`. Two checks:

1. Age ("slopsquatting"): every package newly named in the manifest's dependency sections, and,
   when lockfiles are given, every package name new in the head lockfile (direct or transitive,
   since the lockfile is what `npm ci` installs), must exist on the npm registry and have been
   first published at least MIN_AGE_DAYS ago.
2. Lockfile integrity (offline, on every head entry): `resolved` must be exactly
   `https://registry.npmjs.org/<name>/-/<basename>-<version>.tgz` for the package the entry's
   path names, and `integrity` must be a SHA-2 hash. A lockfile edited to fetch a different
   package, version or host under a familiar name fails here.

A package that passes still needs a reviewer to confirm it is the intended project.

Usage: python scripts/check_new_npm_dependencies.py <base-package.json> <head-package.json>
           [<base-package-lock.json> <head-package-lock.json>]

A base file that does not exist counts as empty (the PR that creates `web/`).
Exit codes: 0 all checks passed, 1 a check failed, 2 registry unreachable.
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
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MIN_AGE_DAYS = 90
REGISTRY_URL = "https://registry.npmjs.org/{name}"
_NAME = re.compile(r"^(@[a-z0-9~-][a-z0-9._~-]*/)?[a-z0-9~-][a-z0-9._~-]*$")
_SECTIONS = ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies")
_TARBALL = "https://registry.npmjs.org/{name}/-/{base}-{version}.tgz"
_INTEGRITY = re.compile(r"^sha(256|384|512)-[A-Za-z0-9+/]+={0,2}$")
# Strict semver, no path or URL syntax: it is interpolated into the tarball URL below.
_VERSION = re.compile(
    r"^\d+\.\d+\.\d+(-[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)?(\+[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)?$"
)
_ALIAS = re.compile(r"^npm:((?:@[a-z0-9~-][a-z0-9._~-]*/)?[a-z0-9~-][a-z0-9._~-]*)@.+$")
_FETCH_WORKERS = 8


def declared_packages(manifest: dict[str, Any]) -> set[str]:
    """Every package named in the manifest's dependency sections."""
    names: set[str] = set()
    for section in _SECTIONS:
        entries = manifest.get(section, {})
        if isinstance(entries, dict):
            names.update(name for name in entries if isinstance(name, str))
    return names


def declared_aliases(manifest: dict[str, Any]) -> dict[str, str]:
    """`{alias: real package}` for `"alias": "npm:real@range"` entries in the manifest."""
    aliases: dict[str, str] = {}
    for section in _SECTIONS:
        entries = manifest.get(section, {})
        if not isinstance(entries, dict):
            continue
        for alias, spec in entries.items():
            match = _ALIAS.match(spec) if isinstance(spec, str) else None
            if match:
                aliases[alias] = match.group(1)
    return aliases


def _entry_name(path: str, entry: dict[str, Any]) -> str:
    """The registry package an entry installs: its `name` (aliases) or its path's last segment."""
    declared = entry.get("name")
    if isinstance(declared, str):
        return declared
    return path.rsplit("node_modules/", 1)[-1]


def lockfile_names(lock: dict[str, Any]) -> set[str]:
    """Registry names of every package the lockfile installs (the root project excluded)."""
    packages = lock.get("packages", {})
    return {
        _entry_name(path, entry)
        for path, entry in packages.items()
        if path and isinstance(entry, dict) and "resolved" in entry
    }


def lockfile_violations(lock: dict[str, Any], aliases: dict[str, str] | None = None) -> list[str]:
    """Why the lockfile cannot be trusted, empty when every entry matches the package it names.

    Fails closed: an unexpected lockfile shape (a version other than 3, a legacy `dependencies`
    tree, no `packages`), any `link` or bundled entry, a `version` that is not plain semver,
    and a `name` that differs from the path (an alias) unless `package.json` declares that
    exact alias at the top level, are all reported.
    """
    problems: list[str] = []
    packages = lock.get("packages")
    if lock.get("lockfileVersion") != 3:
        problems.append("lockfileVersion must be 3 (regenerate with the pinned npm)")
    if "dependencies" in lock:
        problems.append("legacy `dependencies` tree is present; it can disagree with `packages`")
    if not isinstance(packages, dict) or len(packages) < 2:
        problems.append("`packages` is missing or lists no installed package")
        return problems
    allowed_aliases = aliases or {}
    for path, entry in packages.items():
        if not path:
            continue
        if not isinstance(entry, dict):
            problems.append(f"{path}: entry is not an object")
            continue
        if entry.get("link") or entry.get("inBundle"):
            problems.append(f"{path}: link and bundled entries are not allowed")
            continue
        name = _entry_name(path, entry)
        if "name" in entry:
            alias = path.rsplit("node_modules/", 1)[-1]
            top_level = path == f"node_modules/{alias}"
            if not (top_level and allowed_aliases.get(alias) == name):
                problems.append(
                    f"{path}: installs {name!r}, an alias package.json does not declare"
                )
        version = entry.get("version")
        if (
            not _NAME.fullmatch(name)
            or not isinstance(version, str)
            or not _VERSION.fullmatch(version)
        ):
            problems.append(f"{path}: package name or version is not plain npm syntax")
            continue
        expected = _TARBALL.format(name=name, base=name.split("/")[-1], version=version)
        if entry.get("resolved") != expected:
            problems.append(f"{path}: resolved is not {expected}")
        integrity = entry.get("integrity")
        if not isinstance(integrity, str) or not _INTEGRITY.fullmatch(integrity):
            problems.append(f"{path}: integrity is missing or not a SHA-2 hash")
    return problems


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


def _check_age(names: list[str], allow_young: bool) -> int:
    """Judge each name against the registry; 0 all passed, 1 some failed, 2 unreachable."""
    now = datetime.now(UTC)

    def check(name: str) -> Verdict | Exception:
        try:
            return judge(name, fetch_metadata(name), now, allow_young)
        except (urllib.error.URLError, TimeoutError) as error:
            return error

    with ThreadPoolExecutor(max_workers=_FETCH_WORKERS) as pool:
        results = list(pool.map(check, names))
    failed = False
    for name, result in zip(names, results, strict=True):
        if isinstance(result, Exception):
            print(f"::error::Could not reach the npm registry to check {name}: {result}")
            return 2
        level = "notice" if result.ok else "error"
        print(f"::{level}::New npm dependency {result.name}: {result.message}")
        failed = failed or not result.ok
    return 1 if failed else 0


def main(argv: list[str]) -> int:
    if len(argv) not in (3, 5):
        print(__doc__, file=sys.stderr)
        return 2
    base_names = declared_packages(_load(argv[1]))
    head_names = declared_packages(_load(argv[2]))
    added = head_names - base_names
    if len(argv) == 5:
        if not Path(argv[4]).exists():
            print(f"::error::Head lockfile {argv[4]} is missing")
            return 1
        head_lock = _load(argv[4])
        problems = lockfile_violations(head_lock, declared_aliases(_load(argv[2])))
        for problem in problems:
            print(f"::error::Lockfile entry {problem}")
        if problems:
            return 1
        added |= lockfile_names(head_lock) - lockfile_names(_load(argv[3]))
    if not added:
        print("No new npm dependencies.")
        return 0
    allow_young = os.environ.get("ALLOW_YOUNG_PACKAGES", "").lower() == "true"
    status = _check_age(sorted(added), allow_young)
    if status != 2:
        print("A reviewer must confirm each new dependency is the intended, reputable project.")
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv))
