# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""The deploy workflow promotes one attested digest and never rebuilds it (#151)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

WORKFLOWS = Path(".github/workflows")
_TEXT = (WORKFLOWS / "deploy.yml").read_text("utf-8")
_DEPLOY: dict[Any, Any] = yaml.safe_load(_TEXT)
_JOBS: dict[str, Any] = _DEPLOY["jobs"]
_ON = _DEPLOY[True]  # YAML reads the key `on` as True


def _steps(job: str) -> list[dict[str, Any]]:
    return list(_JOBS[job]["steps"])


def _index(job: str, needle: str) -> int:
    for position, step in enumerate(_steps(job)):
        if needle in step.get("run", "") or needle in step.get("name", ""):
            return position
    raise AssertionError(f"{job}: no step mentions {needle!r}")


def test_staging_follows_a_successful_main_build_and_production_follows_a_tag() -> None:
    assert _ON["workflow_run"] == {
        "workflows": ["image-publish"],
        "types": ["completed"],
        "branches": ["main"],
    }
    assert _ON["push"] == {"tags": ["v*"]}
    staging = _JOBS["staging"]
    assert "workflow_run.conclusion == 'success'" in staging["if"]
    assert "head_branch == 'main'" in staging["if"]
    assert staging["environment"] == "staging"
    production = _JOBS["production"]
    assert "startsWith(github.ref, 'refs/tags/v')" in production["if"]
    assert production["environment"] == "production"


def test_permissions_are_per_job_read_only_and_nothing_can_sign() -> None:
    assert _DEPLOY["permissions"] == {}
    for name, job in _JOBS.items():
        granted = job["permissions"]
        assert "id-token" not in granted and "attestations" not in granted, name
        assert "packages" not in granted or granted["packages"] == "read", name
    assert _JOBS["staging"]["permissions"]["contents"] == "read"
    assert _JOBS["production"]["permissions"]["contents"] == "read"
    assert _JOBS["release"]["permissions"] == {"contents": "write"}


def test_every_deploy_follows_a_verified_attestation_from_the_pinned_signer() -> None:
    for job in ("staging", "production"):
        verify = _index(job, "gh attestation verify")
        deploy = _index(job, "deploy_tools.py trigger")
        assert verify < deploy, f"{job}: verify before any deploy"
        command = _steps(job)[verify]["run"]
        assert (
            '--signer-workflow "$GITHUB_REPOSITORY/.github/workflows/image-publish.yml"' in command
        )
        assert "--source-ref refs/heads/main" in command
        assert '--predicate-type "$ATTESTATION_PREDICATE"' in command
    assert _DEPLOY["env"]["ATTESTATION_PREDICATE"] == "https://slsa.dev/provenance/v1"


def test_production_never_rebuilds_and_takes_the_recorded_digest_not_a_tag() -> None:
    assert not re.search(r"build-push-action|docker build|buildx", _TEXT)
    code = "\n".join(line for line in _TEXT.splitlines() if not line.strip().startswith("#"))
    assert "sha-" not in code  # no `sha-` tag is ever resolved
    for job in ("staging", "production"):
        read = _index(job, "gh run download")
        check = _index(job, "check-image")
        assert read <= check < _index(job, "gh attestation verify")
        assert "-n image-digest" in _steps(job)[read]["run"]
        trigger = _steps(job)[_index(job, "deploy_tools.py trigger")]
        assert trigger["env"]["IMAGE"] == "${{ steps.image.outputs.ref }}"
    publish = (WORKFLOWS / "image-publish.yml").read_text("utf-8")
    assert "name: image-digest" in publish and "image-digest.txt" in publish


def test_production_needs_main_a_changelog_section_and_a_passing_staging_deploy() -> None:
    steps = [step.get("run", "") for step in _steps("production")]
    ancestor = _index("production", "merge-base --is-ancestor")
    release = _index("production", "check-release")
    staging = _index("production", "Staging deployed")
    trigger = _index("production", "deploy_tools.py trigger")
    assert max(ancestor, release, staging) < trigger
    assert 'git merge-base --is-ancestor "$GITHUB_SHA" origin/main' in steps[ancestor]
    assert steps[_index("production", "Find the main build run")].count("--branch main") == 1
    assert _steps("production")[0]["with"]["fetch-depth"] == 0
    # The staging run is matched by its title, "staging <build run id>" (run-name).
    assert "format('staging {0}', github.event.workflow_run.id)" in _DEPLOY["run-name"]
    assert "staging $BUILD_RUN_ID" in steps[staging]


def test_a_failing_gate_leaves_production_untouched_and_the_release_waits_for_it() -> None:
    # Every gate is a step before the trigger; a failed step stops the job (no continue-on-error).
    trigger = _index("production", "deploy_tools.py trigger")
    for position, step in enumerate(_steps("production")):
        if position < trigger and "Re-scan" not in step.get("name", ""):
            assert "continue-on-error" not in step, step.get("name")
    assert _JOBS["release"]["needs"] == "production"
    assert "startsWith(github.ref, 'refs/tags/v')" in _JOBS["release"]["if"]
    publish = _steps("release")[-1]["run"]
    assert publish.index("--draft ") < publish.index("--draft=false")


def test_a_pre_release_tag_skips_production_and_is_published_as_a_pre_release() -> None:
    assert "!contains(github.ref_name, '-')" in _JOBS["production"]["if"]
    condition = _JOBS["release"]["if"]
    assert "always()" in condition
    assert "needs.production.result == 'success'" in condition
    assert "needs.production.result == 'skipped'" in condition
    assert "contains(github.ref_name, '-')" in condition
    steps = _steps("release")
    assert any("check-release" in step.get("run", "") for step in steps)
    assert "--prerelease" in steps[-1]["run"]


def test_the_smoke_test_runs_after_each_deploy_and_the_rescan_never_blocks() -> None:
    for job in ("staging", "production"):
        assert _index(job, "deploy_tools.py trigger") < _index(job, "smoke_test.py")
    rescan = next(s for s in _steps("production") if "trivy-action" in s.get("uses", ""))
    assert rescan["continue-on-error"] is True
    assert rescan["with"]["exit-code"] == "0"


def test_hook_urls_and_tokens_are_masked_and_never_echoed() -> None:
    for job in ("staging", "production"):
        assert _index(job, "add-mask") < _index(job, "deploy_tools.py trigger")
    for line in _TEXT.splitlines():
        stripped = line.strip()
        if stripped.startswith(("echo", "printf")) or " echo " in stripped:
            assert "DEPLOY_HOOKS" not in stripped and "SMOKE_TEST_TOKEN" not in stripped
            assert "secrets." not in stripped
    # The secrets only ever reach a step through its own `env:`.
    for job in _JOBS.values():
        for step in job["steps"]:
            assert "secrets." not in step.get("run", "")


def test_untrusted_context_reaches_scripts_only_through_env() -> None:
    risky = re.compile(
        r"\$\{\{[^}]*(github\.event|github\.ref_name|github\.head_ref|github\.actor)"
    )
    for job in _JOBS.values():
        for step in job["steps"]:
            assert not risky.search(step.get("run", "")), step.get("name")


def test_services_equal_the_image_backed_services_of_render_yaml() -> None:
    blueprint = yaml.safe_load(Path("render.yaml").read_text("utf-8"))
    ours = [s["name"] for s in blueprint["services"] if s["type"] in {"web", "cron"}]
    for environment in ("staging", "production"):
        declared = _DEPLOY["env"][f"{environment.upper()}_SERVICES"].split(",")
        assert sorted(declared) == sorted(n for n in ours if n.endswith(environment))


def test_ci_must_have_passed_on_the_commit_before_any_deploy() -> None:
    for job in ("staging", "production"):
        position = _index(job, "--workflow ci.yml")
        assert position < _index(job, "deploy_tools.py trigger")
        assert "continue-on-error" not in _steps(job)[position]


def test_the_staging_job_never_checks_out_the_triggering_run() -> None:
    """CodeQL flags `ref: workflow_run.head_sha`; the scripts come from the default branch."""
    checkout = _steps("staging")[0]
    assert checkout["uses"].startswith("actions/checkout@")
    assert "ref" not in checkout["with"]
    assert checkout["with"]["persist-credentials"] is False
