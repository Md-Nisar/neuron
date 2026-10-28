"""The `web/` scaffold's supply-chain and isolation guarantees (ADR 0010, decisions 2 and 3)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
_EXACT = re.compile(r"^\d+\.\d+\.\d+$")


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((WEB / "package.json").read_text(encoding="utf-8"))
    return loaded


def test_every_dependency_is_pinned_to_an_exact_version(manifest: dict[str, Any]) -> None:
    for section in ("dependencies", "devDependencies"):
        for name, version in manifest[section].items():
            assert _EXACT.match(version), f"{name}@{version} is not an exact version"
    assert not {"optionalDependencies", "peerDependencies"} & manifest.keys()


def test_node_and_package_manager_are_pinned_and_agree(manifest: dict[str, Any]) -> None:
    nvmrc = (WEB / ".nvmrc").read_text(encoding="utf-8").strip()

    assert _EXACT.match(nvmrc)
    assert manifest["engines"]["node"].startswith(f">={nvmrc} <")
    assert re.fullmatch(r"npm@\d+\.\d+\.\d+", manifest["packageManager"])
    assert manifest["private"] is True


def test_lockfile_is_committed_and_installs_run_no_scripts() -> None:
    lock = json.loads((WEB / "package-lock.json").read_text(encoding="utf-8"))
    npmrc = (WEB / ".npmrc").read_text(encoding="utf-8").splitlines()

    assert lock["lockfileVersion"] >= 3
    assert "ignore-scripts=true" in npmrc
    assert "engine-strict=true" in npmrc
    assert "save-exact=true" in npmrc


def test_lockfile_entries_match_the_packages_they_name() -> None:
    from scripts import check_new_npm_dependencies as gate

    lock = json.loads((WEB / "package-lock.json").read_text(encoding="utf-8"))

    assert len(gate.lockfile_names(lock)) > 100
    assert gate.lockfile_violations(lock) == []


def test_typescript_is_strict_and_raw_html_is_banned_by_lint() -> None:
    tsconfig = json.loads((WEB / "tsconfig.json").read_text(encoding="utf-8"))
    eslint = (WEB / "eslint.config.js").read_text(encoding="utf-8")

    assert tsconfig["compilerOptions"]["strict"] is True
    assert "dangerouslySetInnerHTML" in eslint
    assert "strictTypeChecked" in eslint


def test_the_api_image_cannot_contain_web() -> None:
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    rules = [line for line in dockerignore if line and not line.startswith("#")]

    assert rules[0] == "*"  # allowlist: nothing enters unless listed
    assert not [rule for rule in rules if "web" in rule]
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert not re.search(r"^\s*(COPY|ADD)\b.*\bweb\b", dockerfile, re.MULTILINE)


def test_ci_installs_from_the_lockfile_and_runs_every_gate() -> None:
    ci = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    job = ci["jobs"]["web"]
    commands = [step["run"] for step in job["steps"] if "run" in step]

    assert job["defaults"]["run"]["working-directory"] == "web"
    assert job["permissions"] == {"contents": "read"}
    assert commands[0] == "npm ci"
    for gate in ("format:check", "lint", "typecheck", "build", "audit"):
        assert any(gate in command for command in commands), gate
    assert "npm test" in commands
    setup = next(step for step in job["steps"] if "setup-node" in step.get("uses", ""))
    assert setup["with"]["node-version-file"] == "web/.nvmrc"


def test_codeql_scans_the_web_sources() -> None:
    codeql = yaml.safe_load((ROOT / ".github/workflows/codeql.yml").read_text(encoding="utf-8"))

    assert "javascript-typescript" in codeql["jobs"]["analyze"]["strategy"]["matrix"]["language"]


def test_new_npm_packages_face_the_age_check_and_the_lockfile_is_not_counted_as_review() -> None:
    text = (ROOT / ".github/workflows/ai-code-verification.yml").read_text(encoding="utf-8")

    assert "scripts/check_new_npm_dependencies.py" in text
    assert "web/package-lock.json" in text.split("check_new_npm_dependencies.py")[1]
    assert "':(exclude)web/package-lock.json'" in text


def test_makefile_has_a_web_target_per_gate() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    for target in (
        "web-install",
        "web-lint",
        "web-typecheck",
        "web-test",
        "web-build",
        "web-audit",
    ):
        assert re.search(rf"^{target}:", makefile, re.MULTILINE), target
    assert re.search(r"^web:.*web-audit", makefile, re.MULTILINE)
