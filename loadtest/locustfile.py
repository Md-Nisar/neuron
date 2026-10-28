# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Locust scenarios against the reference stack (ADR 0012 decision 5): `make load`.

LOAD_SCENARIO picks `new_thread`, `follow_up`, `approval` or `mix` (60/30/10). Each virtual
user signs in as its own Keycloak test user and sends one run at a time, at most one every
LOAD_THINK_SECONDS. Recorded per run: time to first token (`ttft:<scenario>`) and duration
(`run:<scenario>`), failed by stream `error` code or HTTP status; 4xx rejections are
`rejected:<scenario>`, which the availability SLO does not count.
"""

from __future__ import annotations

import itertools
import os
import time
from typing import Any

import requests
from locust import User, constant_throughput, task

from loadtest.identity import TokenSource, username
from loadtest.shape import StepShape  # noqa: F401  (Locust finds the shape by class)
from loadtest.sse import RunResult, parse_events, summarise

SCENARIO = os.environ.get("LOAD_SCENARIO", "mix")
HOSTS = os.environ.get("LOAD_HOSTS", "http://127.0.0.1:8101,http://127.0.0.1:8102").split(",")
POOL = int(os.environ.get("LOAD_USERS", "50"))
THINK_SECONDS = float(os.environ.get("LOAD_THINK_SECONDS", "10"))
_FOLLOW_UPS_PER_THREAD = 5
_indexes = itertools.count()


class _Session(User):
    abstract = True
    wait_time = constant_throughput(1 / THINK_SECONDS)

    def on_start(self) -> None:
        index = next(_indexes) % POOL
        self.base = HOSTS[index % len(HOSTS)]
        self.tokens = TokenSource(username(index))
        self.http = requests.Session()
        self.http.trust_env = False
        self.thread_id: str | None = None
        self.follow_ups = 0

    def _stream(self, scenario: str, path: str, body: dict[str, Any]) -> RunResult | None:
        started = time.monotonic()
        headers = {"Authorization": f"Bearer {self.tokens.get()}"}
        try:
            with self.http.post(
                f"{self.base}{path}", json=body, headers=headers, stream=True, timeout=120
            ) as response:
                if response.status_code != 200:
                    self._rejected(scenario, response.status_code, started)
                    return None
                lines = response.iter_lines(decode_unicode=True)
                events = list(parse_events((line or "" for line in lines), time.monotonic))
                result = summarise(events, started, time.monotonic())
        except requests.RequestException as exc:
            self._fire(f"run:{scenario}", time.monotonic() - started, 0, exc)
            return None
        failure = None
        if result.outcome == "error":
            failure = RuntimeError(result.error_code or "error")
        elif result.outcome == "incomplete":
            failure = RuntimeError("incomplete_stream")
        if result.ttft_seconds is not None:
            self._fire(f"ttft:{scenario}", result.ttft_seconds, 0, None)
        self._fire(f"run:{scenario}", result.duration_seconds, result.tokens, failure)
        return result

    def _rejected(self, scenario: str, status: int, started: float) -> None:
        elapsed = time.monotonic() - started
        if status >= 500:
            self._fire(f"run:{scenario}", elapsed, 0, RuntimeError(f"http_{status}"))
        else:
            self._fire(f"rejected:{scenario}", elapsed, 0, RuntimeError(f"http_{status}"))

    def _fire(self, name: str, seconds: float, length: int, exception: Exception | None) -> None:
        self.environment.events.request.fire(
            request_type="SSE",
            name=name,
            response_time=seconds * 1000,
            response_length=length,
            exception=exception,
            context={},
        )

    def new_thread(self) -> None:
        result = self._stream("new_thread", "/v1/agent/stream", {"message": "hello"})
        if result is not None:
            self.thread_id, self.follow_ups = result.thread_id, 0

    def follow_up(self) -> None:
        if self.thread_id is None or self.follow_ups >= _FOLLOW_UPS_PER_THREAD:
            result = self._stream("follow_up_seed", "/v1/agent/stream", {"message": "hello"})
            self.thread_id = result.thread_id if result else None
            self.follow_ups = 0
            return
        self.follow_ups += 1
        self._stream(
            "follow_up", "/v1/agent/stream", {"message": "and again", "thread_id": self.thread_id}
        )

    def approval(self) -> None:
        result = self._stream(
            "approval_pause", "/v1/agent/stream", {"message": "remember: load note"}
        )
        if result is None or result.outcome != "approval_required":
            return
        self._stream(
            "approval",
            f"/v1/threads/{result.thread_id}/approvals/{result.approval_id}/stream",
            {"decision": "approve"},
        )


class NewThread(_Session):
    @task
    def go(self) -> None:
        self.new_thread()


class FollowUp(_Session):
    @task
    def go(self) -> None:
        self.follow_up()


class Approval(_Session):
    @task
    def go(self) -> None:
        self.approval()


class Mix(_Session):
    @task(60)
    def a_new_thread(self) -> None:
        self.new_thread()

    @task(30)
    def b_follow_up(self) -> None:
        self.follow_up()

    @task(10)
    def c_approval(self) -> None:
        self.approval()


_CLASSES = {"new_thread": NewThread, "follow_up": FollowUp, "approval": Approval, "mix": Mix}
if SCENARIO not in _CLASSES:
    raise SystemExit(f"LOAD_SCENARIO must be one of {sorted(_CLASSES)}")
for _name, _cls in _CLASSES.items():
    _cls.abstract = _name != SCENARIO
# Locust collects every User subclass in the module namespace, so the loop variable must go.
del _name, _cls
