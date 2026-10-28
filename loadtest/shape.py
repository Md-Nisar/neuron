# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""A step profile: more virtual users every LOAD_STEP_SECONDS until an SLO breaks.

After the first broken step it runs one more step (the failure mode "one step past the knee"),
then stops. Each finished step is appended to LOAD_RESULTS_FILE as one JSON object per line.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict
from pathlib import Path

from locust import LoadTestShape
from locust.stats import StatsError

from loadtest.slo import breaches, summarise_step

STEP_SECONDS = float(os.environ.get("LOAD_STEP_SECONDS", "600"))
STEP_USERS = int(os.environ.get("LOAD_STEP_USERS", "5"))
MAX_STEPS = int(os.environ.get("LOAD_MAX_STEPS", "12"))
RESULTS = Path(os.environ.get("LOAD_RESULTS_FILE", "loadtest-steps.jsonl"))


class StepShape(LoadTestShape):
    def __init__(self) -> None:
        super().__init__()  # type: ignore[no-untyped-call]
        self._step = 0
        self._step_started = time.monotonic()
        self._broken_at: int | None = None
        RESULTS.write_text("", encoding="utf-8")

    def tick(self) -> tuple[int, float] | None:
        assert self.runner is not None  # noqa: S101  # nosec B101  (set before the first tick)
        users = (self._step + 1) * STEP_USERS
        if time.monotonic() - self._step_started < STEP_SECONDS:
            return users, users
        summary = summarise_step(self.runner.stats, users, time.monotonic() - self._step_started)
        found = breaches(summary)
        errors: dict[str, int] = {}
        for error in self.runner.stats.errors.values():
            label = f"{error.name}: {StatsError.parse_error(error.error)}"
            errors[label] = errors.get(label, 0) + error.occurrences
        with RESULTS.open("a", encoding="utf-8") as out:
            out.write(json.dumps({**asdict(summary), "breaches": found, "errors": errors}) + "\n")
        if found and self._broken_at is None:
            self._broken_at = self._step
        self._step += 1
        if self._step >= MAX_STEPS or (
            self._broken_at is not None and self._step > self._broken_at + 1
        ):
            return None
        self.runner.stats.reset_all()
        self._step_started = time.monotonic()
        users = (self._step + 1) * STEP_USERS
        return users, users
