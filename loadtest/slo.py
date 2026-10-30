# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""The SLO check a load step must pass (OPERATIONS.md, "SLOs"). Pure, so it is unit tested."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

TTFT_P90_MS = 15_000.0
RUN_P95_MS = 30_000.0
MAX_FAILURE_RATIO = 0.005  # availability: 99.5%


@dataclass(frozen=True)
class StepSummary:
    users: int
    seconds: float
    runs: int
    failures: int  # 5xx and stream errors; 4xx rejections are not valid events
    ttft_p90_ms: float
    run_p95_ms: float

    @property
    def runs_per_second(self) -> float:
        return self.runs / self.seconds if self.seconds > 0 else 0.0


def breaches(step: StepSummary) -> list[str]:
    """Names of the SLOs this step broke; empty means the step is within them."""
    found = []
    if step.ttft_p90_ms > TTFT_P90_MS:
        found.append("ttft")
    if step.run_p95_ms > RUN_P95_MS:
        found.append("run_duration")
    if step.runs and step.failures / step.runs > MAX_FAILURE_RATIO:
        found.append("availability")
    return found


def summarise_step(stats: Any, users: int, seconds: float) -> StepSummary:
    """Fold Locust's per-name stats for one step into a `StepSummary`."""
    runs = failures = 0
    ttft_p90 = run_p95 = 0.0
    for (name, _), entry in stats.entries.items():
        if name.startswith("run:"):
            runs += entry.num_requests
            failures += entry.num_failures
            run_p95 = max(run_p95, entry.get_response_time_percentile(0.95) or 0.0)
        elif name.startswith("ttft:"):
            ttft_p90 = max(ttft_p90, entry.get_response_time_percentile(0.90) or 0.0)
    return StepSummary(users, seconds, runs, failures, ttft_p90, run_p95)
