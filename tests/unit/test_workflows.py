# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""ai-review and nightly-eval share one NVIDIA key and must not run together (issue #157)."""

from __future__ import annotations

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
