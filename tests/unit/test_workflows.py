# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""ai-review and nightly-eval share one NVIDIA key and must not run together (issue #157)."""

from __future__ import annotations

import datetime
import re
from pathlib import Path
from typing import Any

import yaml

WORKFLOWS = Path(".github/workflows")


def _load(name: str) -> dict[Any, Any]:
    loaded = yaml.safe_load((WORKFLOWS / name).read_text("utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _minutes(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def test_both_workflows_use_the_same_secret_name_and_no_second_key() -> None:
    for name in ("ai-review.yml", "nightly-eval.yml"):
        text = (WORKFLOWS / name).read_text("utf-8")
        assert "secrets.NVIDIA_API_KEY" in text
        assert text.count("secrets.NVIDIA") == text.count("secrets.NVIDIA_API_KEY")
        assert "echo $NVIDIA" not in text and 'echo "$NVIDIA' not in text


def test_ai_review_skips_during_the_nightly_window() -> None:
    nightly = _load("nightly-eval.yml")
    review = _load("ai-review.yml")
    cron = nightly[True]["schedule"][0]["cron"]
    minute, hour = (int(part) for part in cron.split()[:2])
    start_run = hour * 60 + minute
    cap = nightly["jobs"]["live-eval"]["timeout-minutes"]

    steps = review["jobs"]["review"]["steps"]
    guard = next(s for s in steps if s.get("id") == "window")
    window_start = _minutes(guard["env"]["NIGHTLY_WINDOW_START_UTC"])
    window_end = _minutes(guard["env"]["NIGHTLY_WINDOW_END_UTC"])
    # The window opens before the nightly starts and closes after its timeout.
    assert window_start <= start_run
    assert window_end >= start_run + cap
    # Every step after the guard is skipped, and the guard never fails the job.
    assert "exit 1" not in guard["run"]
    for step in steps:
        if step is not guard:
            assert step["if"] == "steps.window.outputs.skip != 'true'"
    # The review job never touches the nightly concurrency group, so neither can cancel or
    # replace the other.
    assert review["concurrency"]["group"].startswith("ai-review-")
    assert nightly["concurrency"]["group"] == "nightly-eval"
    assert nightly["concurrency"]["cancel-in-progress"] is False


def test_nightly_timeout_leaves_headroom_over_the_measured_run() -> None:
    cap = _load("nightly-eval.yml")["jobs"]["live-eval"]["timeout-minutes"]
    assert cap >= 74 + 30


def test_nightly_checks_the_model_before_the_evals_and_prints_only_a_status() -> None:
    steps = _load("nightly-eval.yml")["jobs"]["live-eval"]["steps"]
    names = [step.get("name", "") for step in steps]
    probe = steps[names.index("Check the model is reachable")]
    assert names.index("Check the model is reachable") < names.index("Run the live evals")
    assert probe["env"]["NVIDIA_API_KEY"] == "${{ secrets.NVIDIA_API_KEY }}"
    script = probe["run"]
    # The model comes from the workflow's APP_DEFAULT_MODEL, never a second copy of its name.
    assert "APP_DEFAULT_MODEL" in script
    # The response body can name the account or model; only the status code is printed.
    assert "-o /dev/null" in script and "%{http_code}" in script


def _uses_lines() -> list[tuple[str, str]]:
    found = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for line in path.read_text("utf-8").splitlines():
            stripped = line.strip().removeprefix("- ")
            if stripped.startswith("uses:"):
                found.append((path.name, stripped))
    return found


_PINNED = re.compile(r"^uses: [\w.-]+/[\w./-]+@[0-9a-f]{40} # v\d+\.\d+\.\d+$")


def test_every_action_is_pinned_to_a_commit_sha_with_a_version_comment() -> None:
    uses = _uses_lines()
    assert uses
    for name, line in uses:
        if line.startswith(("uses: ./", "uses: docker://")):
            continue  # local and docker:// actions are out of scope
        assert _PINNED.match(line), f"{name}: {line}"


def test_the_pin_check_rejects_tag_and_branch_references() -> None:
    sha = "fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09"
    assert _PINNED.match(f"uses: actions/checkout@{sha} # v5.1.0")
    assert not _PINNED.match("uses: actions/checkout@v5")
    assert not _PINNED.match("uses: actions/checkout@main")
    assert not _PINNED.match(f"uses: actions/checkout@{sha}")


def test_dependabot_covers_four_ecosystems_weekly_grouped_with_cooldown() -> None:
    config = yaml.safe_load(Path(".github/dependabot.yml").read_text("utf-8"))
    assert config["version"] == 2
    updates = {u["package-ecosystem"]: u for u in config["updates"]}
    assert set(updates) == {"uv", "github-actions", "docker", "npm"}
    for update in updates.values():
        assert update["schedule"]["interval"] == "weekly"
        assert update["cooldown"]["default-days"] == 7
        assert update["groups"]


def test_nothing_auto_merges() -> None:
    forbidden = ("--auto", "auto-merge", "automerge", "gh pr merge")
    for path in sorted(WORKFLOWS.glob("*.yml")):
        text = path.read_text("utf-8").lower()
        for token in forbidden:
            assert token not in text, f"{path.name} contains {token}"
    dependabot = Path(".github/dependabot.yml").read_text("utf-8").lower()
    assert "auto-merge" not in dependabot and "automerge" not in dependabot


def test_docker_build_workflow_only_builds() -> None:
    workflow = _load("docker-build.yml")
    text = (WORKFLOWS / "docker-build.yml").read_text("utf-8")
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow[True]["push"]["branches"] == ["main"]
    paths = workflow[True]["pull_request"]["paths"]
    assert {"Dockerfile", ".dockerignore", "pyproject.toml", "uv.lock"} <= set(paths)
    job = workflow["jobs"]["docker-build"]
    assert job["timeout-minutes"] <= 20
    assert "secrets." not in text and "docker login" not in text and "login-action" not in text
    assert {"src/**", "tests/integration/test_image_layout.py"} <= set(paths)
    steps = job["steps"]
    named = {s["name"]: s for s in steps if "name" in s}
    build = named["Build image"]
    assert build["run"].count("docker build") == 1  # built once, then reused
    assert "-t neuron-test ." in build["run"]
    assert build["env"] == {"GIT_SHA": "${{ github.sha }}"}
    # Only labels are passed as build arguments, never anything secret-looking.
    assert re.findall(r'--build-arg "(\w+)=', text) == ["GIT_SHA", "VERSION"]
    smoke = named["Import smoke"]["run"]
    assert smoke.startswith("docker run --rm --entrypoint python neuron-test -c ")
    assert "-e " not in smoke and "--env" not in smoke and "-v " not in smoke
    layout = named["Image layout test"]["run"]
    assert "tests/integration/test_image_layout.py" in layout and "-m docker" in layout
    stale = named["Build fails on a stale uv.lock"]["run"]
    assert "docker build" in stale and "exit 1" in stale and "needs to be updated" in stale
    assert "docker push" not in text and "--push" not in text


# --- image-publish.yml (issue #140, ADR 0008 decision 6) -------------------------------------

_MAX_IGNORE_DAYS = 90


def _publish_jobs() -> dict[str, Any]:
    jobs = _load("image-publish.yml")["jobs"]
    assert isinstance(jobs, dict)
    return jobs


def _step_with(job: dict[str, Any], uses_prefix: str) -> dict[str, Any]:
    matches = [s for s in job["steps"] if str(s.get("uses", "")).startswith(uses_prefix)]
    assert len(matches) == 1, uses_prefix
    with_ = matches[0]["with"]
    assert isinstance(with_, dict)
    return with_


def test_image_publish_runs_only_on_pushes_to_main() -> None:
    workflow = _load("image-publish.yml")
    assert workflow[True] == {"push": {"branches": ["main"]}}
    assert workflow["permissions"] == {}
    for job in _publish_jobs().values():
        assert "permissions" in job  # every job states its own permissions
    assert _publish_jobs()["build-push"]["if"] == "github.ref == 'refs/heads/main'"
    # Pull requests are built, without a push, by docker-build.yml, which has no registry access.
    docker_build = (WORKFLOWS / "docker-build.yml").read_text("utf-8")
    assert "pull_request" in docker_build and "packages:" not in docker_build


def test_image_publish_permissions_are_per_job_and_minimal() -> None:
    jobs = _publish_jobs()
    assert jobs["build-push"]["permissions"] == {"contents": "read", "packages": "write"}
    assert jobs["scan"]["permissions"] == {"contents": "read", "packages": "read"}
    assert jobs["attest"]["permissions"] == {
        "contents": "read",
        "packages": "write",
        "id-token": "write",
        "attestations": "write",
    }


def test_only_image_publish_holds_id_token_or_attestations_write() -> None:
    for path in sorted(WORKFLOWS.glob("*.yml")):
        if path.name == "image-publish.yml":
            continue
        text = path.read_text("utf-8")
        assert "id-token" not in text, path.name
        assert "attestations" not in text, path.name
        assert "packages: write" not in text, path.name


def test_image_publish_builds_with_provenance_and_sbom_and_no_secret_argument() -> None:
    build = _step_with(_publish_jobs()["build-push"], "docker/build-push-action@")
    assert build["push"] is True
    assert build["provenance"] == "mode=max"
    assert build["sbom"] is True
    assert build["tags"] == "${{ env.IMAGE }}:sha-${{ github.sha }}"
    args = dict(line.split("=", 1) for line in build["build-args"].splitlines())
    assert args == {
        "GIT_SHA": "${{ github.sha }}",
        "VERSION": "${{ steps.version.outputs.value }}",
    }
    assert "secret-files" not in build and "secrets" not in build
    text = (WORKFLOWS / "image-publish.yml").read_text("utf-8")
    assert set(re.findall(r"secrets\.(\w+)", text)) == {"GITHUB_TOKEN"}
    assert _load("image-publish.yml")["env"] == {"IMAGE": "ghcr.io/md-nisar/neuron"}


def test_image_scan_fails_on_fixable_high_and_critical_and_on_a_database_failure() -> None:
    jobs = _publish_jobs()
    scan = _step_with(jobs["scan"], "aquasecurity/trivy-action@")
    assert scan["image-ref"] == "${{ env.IMAGE }}@${{ needs.build-push.outputs.digest }}"
    assert scan["severity"] == "HIGH,CRITICAL"
    assert scan["ignore-unfixed"] is True
    assert scan["exit-code"] == "1"
    assert scan["trivyignores"] == ".trivyignore.yaml"
    # A cached database could stand in for one that failed to update.
    assert scan["cache"] is False
    assert "skip-setup-trivy" not in scan
    assert not [key for key in scan if key.startswith("skip")]
    text = (WORKFLOWS / "image-publish.yml").read_text("utf-8").lower()
    assert "skip-db-update" not in text and "skip_db_update" not in text
    assert "continue-on-error" not in text and "|| true" not in text
    assert jobs["scan"]["needs"] == "build-push"


def test_attestation_needs_the_scan_and_attests_the_pushed_digest_to_the_registry() -> None:
    attest = _publish_jobs()["attest"]
    assert set(attest["needs"]) == {"build-push", "scan"}
    step = _step_with(attest, "actions/attest@")
    assert step["subject-name"] == "${{ env.IMAGE }}"
    assert step["subject-digest"] == "${{ needs.build-push.outputs.digest }}"
    assert step["push-to-registry"] is True
    # No predicate input: the default is SLSA build provenance (the verify command's type).
    assert not {"predicate", "predicate-type", "predicate-path", "sbom-path"} & set(step)
    assert attest["outputs"] == {"digest": "${{ needs.build-push.outputs.digest }}"}


def _ignore_problems(entries: list[dict[str, Any]], today: datetime.date) -> list[str]:
    problems = []
    for entry in entries:
        name = str(entry.get("id", "<no id>"))
        if not entry.get("id"):
            problems.append(f"{name}: id is missing")
        if not str(entry.get("statement", "")).strip():
            problems.append(f"{name}: statement (the reason) is missing")
        expires = entry.get("expired_at")
        if isinstance(expires, datetime.datetime):  # a YAML timestamp; a subclass of date
            expires = expires.date()
        if not isinstance(expires, datetime.date):
            problems.append(f"{name}: expired_at is missing or not a date")
        elif expires > today + datetime.timedelta(days=_MAX_IGNORE_DAYS):
            problems.append(f"{name}: expired_at is more than {_MAX_IGNORE_DAYS} days out")
    return problems


def test_image_scan_ignores_have_a_reason_and_a_review_date_within_90_days() -> None:
    loaded = yaml.safe_load(Path(".trivyignore.yaml").read_text("utf-8"))
    assert set(loaded) == {"vulnerabilities"}
    assert isinstance(loaded["vulnerabilities"], list)
    assert _ignore_problems(loaded["vulnerabilities"], datetime.date.today()) == []
    # The only ignore file: no other one is passed to the scanner.
    assert sorted(p.name for p in Path(".").glob(".trivyignore*")) == [".trivyignore.yaml"]


def test_the_ignore_rule_rejects_missing_reasons_and_dates_that_are_too_far_out() -> None:
    today = datetime.date(2026, 10, 22)
    good = {"id": "CVE-1", "statement": "not reachable", "expired_at": datetime.date(2027, 1, 20)}
    assert _ignore_problems([good], today) == []
    assert _ignore_problems([{**good, "expired_at": datetime.date(2027, 1, 21)}], today)
    assert _ignore_problems([{**good, "statement": " "}], today)
    assert _ignore_problems([{k: v for k, v in good.items() if k != "expired_at"}], today)
    assert _ignore_problems([{**good, "expired_at": "2027-01-20"}], today)
    # A YAML timestamp loads as a datetime: compared by date, not a TypeError.
    late = datetime.datetime(2027, 1, 21, 9, 30)
    assert _ignore_problems([{**good, "expired_at": late}], today)
    assert _ignore_problems([{**good, "expired_at": late.replace(day=20)}], today) == []
    assert _ignore_problems([{**good, "id": ""}], today)


def test_docs_describe_the_scan_database_the_workflow_and_the_verify_command() -> None:
    security = Path("SECURITY.md").read_text("utf-8")
    assert "downloaded at run time" in security
    assert ".trivyignore.yaml" in security
    assert "image-publish.yml" in Path("docs/AI_CODE_VERIFICATION.md").read_text("utf-8")
    operations = Path("OPERATIONS.md").read_text("utf-8")
    assert "gh attestation verify oci://ghcr.io/md-nisar/neuron@" in operations
    assert "--signer-workflow Md-Nisar/neuron/.github/workflows/image-publish.yml" in operations
    assert "--predicate-type https://slsa.dev/provenance/v1" in operations


# --- ci.yml observability-config (issue #155) -------------------------------------------------


def test_ci_validates_alert_rules_and_collector_config_with_the_pinned_script() -> None:
    workflow = _load("ci.yml")
    text = (WORKFLOWS / "ci.yml").read_text("utf-8")
    job = workflow["jobs"]["observability-config"]
    assert workflow["permissions"] == {"contents": "read"}
    assert job["permissions"] == {"contents": "read"}
    assert job["runs-on"] == "ubuntu-latest" and job["timeout-minutes"] <= 10
    assert "secrets." not in text
    runs = [step["run"] for step in job["steps"] if "run" in step]
    assert any("validate_observability.py check" in run for run in runs)
    assert any("validate_observability.py reject-broken" in run for run in runs)
    # The binaries come from the script's pins, never from a package manager or `latest`.
    assert not any(token in " ".join(runs) for token in ("apt", "brew", "curl", "latest"))
    checkout = next(s for s in job["steps"] if s.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"] == {"persist-credentials": False}
    typecheck = [
        s["run"] for s in workflow["jobs"]["checks"]["steps"] if "mypy" in s.get("run", "")
    ]
    assert len(typecheck) == 1 and "scripts/validate_observability.py" in typecheck[0]
