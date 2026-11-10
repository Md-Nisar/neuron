# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Ingestion and search figures on the reference stack (RAG-08.05). Local use only.

    KNOWLEDGE_ENABLED=true NEURON_IMAGE=neuron:ref make reference-up
    KNOWLEDGE_ENABLED=true NEURON_IMAGE=neuron:ref docker compose \
        -f docker-compose.reference.yml --profile knowledge up -d --no-deps worker
    uv run python -m scripts.knowledge_load > figures.json

Figures, not a gate (RAG-09.06 adds one). Each user creates a base and uploads Markdown files,
at most `knowledge_max_ingesting_per_user` (5) in flight; a document's ingestion time is its
`updated_at - created_at` on the server once it is `ready`. Then every user searches its base
through `POST /v1/knowledge/search` at a fixed pace under the per-user rate limit, and the client
records each call's latency. Embeddings are the fake provider's and only the Markdown parser runs,
so the figures cover the queue, chunking, storage and retrieval, not a provider or docling.
Deletes the bases it created.
"""

from __future__ import annotations

import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any

from loadtest.identity import TokenSource, provision_users, username
from scripts.dr_drill import API, api
from scripts.smoke_test import SmokeFailure, _request

USERS = 8
DOCUMENTS_PER_USER = 10
IN_FLIGHT = 5
PARAGRAPHS = 60  # about 16 KB of Markdown, several chunks per document
SEARCH_SECONDS = 60
SEARCH_INTERVAL = 1.25  # 48 a minute per user, under the default 60
FIRST_USER = 960  # clear of the load test's and the drill's users
QUERIES = ("lighthouse keeper duties", "tide tables", "storm log", "lamp maintenance")


def markdown(user: int, doc: int) -> bytes:
    """A synthetic document; every paragraph differs, so no two chunks are duplicates."""
    lines = [f"# Station report {user}-{doc}\n"]
    for p in range(PARAGRAPHS):
        topic = QUERIES[p % len(QUERIES)]
        lines.append(
            f"## Entry {p}\n\nOn day {p} of report {user}-{doc} the {topic} were reviewed. "
            f"The keeper noted wind from bearing {(p * 37) % 360} and visibility of {p % 9} miles, "
            f"and the relief crew logged item {user * 1000 + doc * 100 + p} for the archive. "
            "Fuel, wicks and the clockwork were checked against the station's standing orders.\n"
        )
    return "\n".join(lines).encode()


def documents(token: str, kb_id: str) -> list[dict[str, Any]]:
    status, text = api("GET", f"/v1/knowledge/bases/{kb_id}/documents?limit=100", token)
    return list(json.loads(text)["documents"]) if status == 200 else []


def ingest(user: int) -> dict[str, Any]:
    source = TokenSource(username(user))
    kb = _request("base", "POST", API, "/v1/knowledge/bases", 30, token=source.get(),
                  body={"name": f"load {user}"})  # fmt: skip
    kb_id, path = str(kb["kb_id"]), f"/v1/knowledge/bases/{kb['kb_id']}/documents"
    sent = refused = 0
    while True:
        docs = documents(source.get(), kb_id)
        busy = sum(d["status"] not in {"ready", "failed"} for d in docs)
        while sent < DOCUMENTS_PER_USER and busy < IN_FLIGHT:
            content = markdown(user, sent)
            try:
                _request("upload", "POST", API, path, 60, token=source.get(),
                         upload=(f"report-{sent}.md", content))  # fmt: skip
            except SmokeFailure as exc:  # 429: the ingesting cap counts jobs not yet settled
                if "HTTP 429" not in str(exc):
                    raise
                refused += 1
                break
            sent, busy = sent + 1, busy + 1
        if sent == DOCUMENTS_PER_USER and busy == 0 and len(docs) == DOCUMENTS_PER_USER:
            return {"user": user, "kb_id": kb_id, "documents": docs, "refused": refused}
        time.sleep(2)


def seconds(doc: dict[str, Any]) -> float:
    start, end = (datetime.fromisoformat(doc[k]) for k in ("created_at", "updated_at"))
    return (end - start).total_seconds()


def search(user: int, kb_id: str, deadline: float) -> list[tuple[int, float]]:
    source, calls, index = TokenSource(username(user)), [], 0
    while time.monotonic() < deadline:
        began = time.monotonic()
        body = {"query": QUERIES[index % len(QUERIES)], "kb_ids": [kb_id], "limit": 5}
        status, _ = api("POST", "/v1/knowledge/search", source.get(), body)
        calls.append((status, time.monotonic() - began))
        index += 1
        time.sleep(max(0.0, SEARCH_INTERVAL - (time.monotonic() - began)))
    return calls


def percentile(values: list[float], share: float) -> float:
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(share * len(ordered)))], 3)


def main() -> int:
    users = range(FIRST_USER, FIRST_USER + USERS)
    provision_users(FIRST_USER + USERS)
    began = time.monotonic()
    with ThreadPoolExecutor(USERS) as pool:
        bases = list(pool.map(ingest, users))
    wall = time.monotonic() - began
    docs = [d for b in bases for d in b["documents"]]
    ready = [seconds(d) for d in docs if d["status"] == "ready"]
    deadline = time.monotonic() + SEARCH_SECONDS
    with ThreadPoolExecutor(USERS) as pool:
        calls = [c for r in pool.map(search, users, [b["kb_id"] for b in bases],
                                     [deadline] * USERS) for c in r]  # fmt: skip
    ok = [latency for status, latency in calls if status == 200]
    for base in bases:
        api(
            "DELETE",
            f"/v1/knowledge/bases/{base['kb_id']}",
            TokenSource(username(base["user"])).get(),
        )
    report = {
        "ingestion": {
            "users": USERS, "documents": len(docs), "ready": len(ready),
            "failed": sum(d["status"] == "failed" for d in docs),
            "uploads_refused_429": sum(b["refused"] for b in bases),
            "bytes_per_document": len(markdown(0, 0)), "in_flight_per_user": IN_FLIGHT,
            "wall_seconds": round(wall, 1), "documents_per_minute": round(len(docs) / wall * 60, 1),
            "seconds_p50": percentile(ready, 0.5), "seconds_p95": percentile(ready, 0.95),
            "seconds_max": round(max(ready), 3),
        },
        "search": {
            "users": USERS, "seconds": SEARCH_SECONDS, "calls": len(calls), "ok": len(ok),
            "statuses": sorted({s for s, _ in calls}),
            "per_second": round(len(calls) / SEARCH_SECONDS, 1),
            "latency_p50": percentile(ok, 0.5), "latency_p95": percentile(ok, 0.95),
            "latency_p99": percentile(ok, 0.99), "latency_mean": round(statistics.mean(ok), 3),
        },
    }  # fmt: skip
    print(json.dumps(report, indent=2))
    return 0 if len(ready) == len(docs) and len(ok) == len(calls) else 1


if __name__ == "__main__":
    raise SystemExit(main())
