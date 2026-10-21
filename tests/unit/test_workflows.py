# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""ai-review and nightly-eval share one NVIDIA key and must not run together (issue #157)."""

from __future__ import annotations

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


def test_dependabot_covers_three_ecosystems_weekly_grouped_with_cooldown() -> None:
    config = yaml.safe_load(Path(".github/dependabot.yml").read_text("utf-8"))
    assert config["version"] == 2
    updates = {u["package-ecosystem"]: u for u in config["updates"]}
    assert set(updates) == {"uv", "github-actions", "docker"}
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
    runs = [s["run"] for s in job["steps"] if "run" in s]
    assert runs == ["docker build -t neuron-test ."]
    assert "push" not in runs[0] and "--push" not in text
