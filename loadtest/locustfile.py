# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Locust scenarios against the reference stack (ADR 0012 decision 5): `make load`.

LOAD_SCENARIO picks `new_thread`, `follow_up`, `approval` or `mix` (60/30/10); the knowledge
scenarios (RAG-09.06) are `knowledge` (uploads and search) and `chat_search` (`mix` beside search):
see `loadtest/run_knowledge.sh`. Each virtual
user signs in as its own Keycloak test user and sends one run at a time, at most one every
LOAD_THINK_SECONDS. Recorded per run: time to first token (`ttft:<scenario>`) and duration
(`run:<scenario>`), failed by stream `error` code or HTTP status; 4xx rejections are
`rejected:<scenario>`, which the availability SLO does not count.
"""

from __future__ import annotations

import itertools
import json
import os
import time
from pathlib import Path
from typing import Any

import requests
from locust import User, constant_throughput, events, task

from loadtest import knowledge
from loadtest.identity import KNOWLEDGE_FIRST_USER, TokenSource, username
from loadtest.shape import StepShape  # noqa: F401  (Locust finds the shape by class)
from loadtest.sse import RunResult, parse_events, summarise

SCENARIO = os.environ.get("LOAD_SCENARIO", "mix")
HOSTS = os.environ.get("LOAD_HOSTS", "http://127.0.0.1:8101,http://127.0.0.1:8102").split(",")
POOL = int(os.environ.get("LOAD_USERS", "50"))
THINK_SECONDS = float(os.environ.get("LOAD_THINK_SECONDS", "10"))
_FOLLOW_UPS_PER_THREAD = 5
_indexes = itertools.count()
SEARCH_USERS = int(os.environ.get("LOAD_SEARCH_USERS", "5"))
SEARCH_SECONDS = float(os.environ.get("LOAD_SEARCH_SECONDS", "1.25"))  # under 60 a minute
UPLOAD_SECONDS = float(os.environ.get("LOAD_UPLOAD_SECONDS", "3"))
INGESTION_FILE = Path(os.environ.get("LOAD_INGESTION_FILE", "loadtest-ingestion.json"))
_knowledge_indexes = itertools.count()
_bases: list[tuple[str, TokenSource, str, bool]] = []  # host, user, kb_id, upload user


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


class _Knowledge(User):
    """A user with its own base; `upload` and `search` are timed, a 4xx is `rejected:<name>`."""

    abstract = True
    uploads = False

    def on_start(self) -> None:
        self.index = KNOWLEDGE_FIRST_USER + next(_knowledge_indexes)
        self.host_url = HOSTS[self.index % len(HOSTS)]
        self.tokens = TokenSource(username(self.index))
        self.http = requests.Session()
        self.http.trust_env = False
        self.sent = 0
        response = self._call("base", "POST", "/v1/knowledge/bases", json={"name": "load"})
        if response is None:
            raise RuntimeError("could not create a knowledge base")
        self.kb_id = str(response.json()["kb_id"])
        _bases.append((self.host_url, self.tokens, self.kb_id, self.uploads))

    def _call(self, name: str, method: str, path: str, **kwargs: Any) -> requests.Response | None:
        started = time.monotonic()
        headers = {"Authorization": f"Bearer {self.tokens.get()}"}
        error: Exception | None = None
        try:
            response = self.http.request(
                method, f"{self.host_url}{path}", headers=headers, timeout=60, **kwargs
            )
        except requests.RequestException as exc:
            response, error = None, exc
        elapsed = (time.monotonic() - started) * 1000
        if response is not None and 400 <= response.status_code < 500:
            name, error = f"rejected:{name}", RuntimeError(f"http_{response.status_code}")
        elif response is not None and response.status_code >= 500:
            error = RuntimeError(f"http_{response.status_code}")
        self.environment.events.request.fire(
            request_type="HTTP", name=name, response_time=elapsed,
            response_length=0, exception=error, context={},
        )  # fmt: skip
        return response if error is None else None

    def upload(self) -> bool:
        content = knowledge.document(self.index, self.sent)
        files = {"file": (f"report-{self.sent}.txt", content, "text/plain")}
        path = f"/v1/knowledge/bases/{self.kb_id}/documents"
        if self._call("upload", "POST", path, files=files) is None:
            return False  # 429 while the base has its maximum in flight
        self.sent += 1
        return True


class KnowledgeUpload(_Knowledge):
    uploads = True
    wait_time = constant_throughput(1 / UPLOAD_SECONDS)

    @task
    def go(self) -> None:
        self.upload()


class KnowledgeSearch(_Knowledge):
    """Filtered hybrid search of its own base, which holds one ingested document."""

    fixed_count = SEARCH_USERS
    wait_time = constant_throughput(1 / SEARCH_SECONDS)

    def on_start(self) -> None:
        super().on_start()
        while not self.upload():
            time.sleep(2)
        self.queries = itertools.cycle(knowledge.QUERIES)

    @task
    def go(self) -> None:
        body = {"query": next(self.queries), "kb_ids": [self.kb_id], "limit": 5}
        self._call("search", "POST", "/v1/knowledge/search", json=body)


_CLASSES: dict[str, tuple[type[User], ...]] = {
    "new_thread": (NewThread,),
    "follow_up": (FollowUp,),
    "approval": (Approval,),
    "mix": (Mix,),
    "knowledge": (KnowledgeUpload, KnowledgeSearch),
    "chat_search": (Mix, KnowledgeSearch),
}
if SCENARIO not in _CLASSES:
    raise SystemExit(f"LOAD_SCENARIO must be one of {sorted(_CLASSES)}")
for _cls in (NewThread, FollowUp, Approval, Mix, KnowledgeUpload, KnowledgeSearch):
    _cls.abstract = _cls not in _CLASSES[SCENARIO]
# Locust collects every User subclass in the module namespace, so the loop variable must go.
del _cls


@events.test_stop.add_listener  # type: ignore[untyped-decorator]
def _report(**_: Any) -> None:
    """Wait for the upload users' documents to settle, record ingestion, delete every base."""
    if not _bases:
        return
    docs: list[dict[str, Any]] = []
    deadline = time.monotonic() + 600
    for host, tokens, kb_id, uploads in _bases:
        session = requests.Session()
        session.trust_env = False
        session.headers["Connection"] = "close"  # polls are seconds apart, past keep-alive
        url = f"{host}/v1/knowledge/bases/{kb_id}"
        while uploads:
            found = _documents(session, url, tokens)
            settled = all(d["status"] in {"ready", "failed"} for d in found)
            if settled or time.monotonic() > deadline:
                docs.extend(found)
                break
            time.sleep(5)
        session.delete(url, headers={"Authorization": f"Bearer {tokens.get()}"}, timeout=60)
    if docs:
        INGESTION_FILE.write_text(json.dumps(knowledge.ingestion(docs), indent=2) + "\n")


def _documents(session: requests.Session, url: str, tokens: TokenSource) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    while True:
        response = session.get(
            f"{url}/documents?limit=100&offset={len(found)}",
            headers={"Authorization": f"Bearer {tokens.get()}"},
            timeout=60,
        )
        if response.status_code == 429:
            time.sleep(5)
            continue
        response.raise_for_status()
        page = response.json()["documents"]
        found.extend(page)
        if len(page) < 100:
            return found
