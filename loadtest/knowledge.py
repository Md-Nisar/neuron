# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Knowledge load scenarios' fixture, ingestion report and baseline (RAG-09.06).

The fixture is synthetic plain text with a form feed between pages, so the worker's own text
parser counts pages without docling (the "fake parser"); the stack's fake embeddings embed it.
`ingestion` folds the documents of the upload users' bases into pages per minute, from the
server's timestamps. `python -m loadtest.knowledge baseline --steps DIR > FILE` prints the
baseline: search p50/p95 and ingestion from the `knowledge` run, and chat p95 alone (`mix`)
and beside search load (`chat_search`), with the host.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from loadtest.baseline import host_description

PAGES = int(os.environ.get("LOAD_KNOWLEDGE_PAGES", "8"))
QUERIES = ("lighthouse keeper duties", "tide tables", "storm log", "lamp maintenance")
_PARAGRAPHS_PER_PAGE = 6


def document(user: int, doc: int, pages: int = PAGES) -> bytes:
    """A synthetic report, no real data; every paragraph differs, so no chunk repeats."""
    out = []
    for page in range(pages):
        lines = [f"Station report {user}-{doc}, page {page + 1}"]
        for p in range(_PARAGRAPHS_PER_PAGE):
            topic = QUERIES[(page + p) % len(QUERIES)]
            lines.append(
                f"On day {page * 10 + p} of report {user}-{doc} the {topic} were reviewed. The "
                f"keeper noted wind from bearing {(page * 37 + p) % 360} and visibility of "
                f"{p % 9} miles, and logged item {user * 10_000 + doc * 100 + page}."
            )
        out.append("\n\n".join(lines))
    return "\n\f".join(out).encode()


def _percentile(values: list[float], share: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(share * len(ordered)))], 3)


def ingestion(docs: list[dict[str, Any]]) -> dict[str, Any]:
    """Pages and documents per minute over the span from the first upload to the last `ready`."""
    ready = [d for d in docs if d["status"] == "ready"]
    times = [
        (datetime.fromisoformat(d["created_at"]), datetime.fromisoformat(d["updated_at"]))
        for d in ready
    ]
    seconds = [(end - start).total_seconds() for start, end in times]
    span = (max(e for _, e in times) - min(s for s, _ in times)).total_seconds() if times else 0
    pages = sum(int(d["page_count"] or 0) for d in ready)
    return {
        "documents": len(docs),
        "ready": len(ready),
        "failed": sum(d["status"] == "failed" for d in docs),
        "unsettled": len(docs) - len(ready) - sum(d["status"] == "failed" for d in docs),
        "pages": pages,
        "span_seconds": round(span, 1),
        "pages_per_minute": round(pages / span * 60, 1) if span else 0.0,
        "documents_per_minute": round(len(ready) / span * 60, 1) if span else 0.0,
        "document_seconds_p50": _percentile(seconds, 0.5),
        "document_seconds_p95": _percentile(seconds, 0.95),
    }


def _step(path: Path) -> dict[str, Any]:
    """The last finished step of a fixed-load run (LOAD_MAX_STEPS=1 writes one)."""
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
    return dict(json.loads(lines[-1]))


def baseline(steps: Path, image: str, note: str, host: str | None = None) -> dict[str, Any]:
    knowledge, alone, beside = (
        _step(steps / f"{n}.jsonl") for n in ("knowledge", "mix", "chat_search")
    )
    search = knowledge["requests"].get("search", {})
    report = json.loads((steps / "knowledge.ingestion.json").read_text(encoding="utf-8"))
    before, after = alone["run_p95_ms"], beside["run_p95_ms"]
    return {
        "image": image,
        "host": host or host_description(),
        "memory_gb": _memory_gb(),
        "note": note,
        "search": {
            "users": int(os.environ.get("LOAD_SEARCH_USERS", "0")) or None,
            "seconds": round(knowledge["seconds"]),
            "calls": search.get("requests", 0),
            "failures": search.get("failures", 0),
            "rejected_429": knowledge["requests"].get("rejected:search", {}).get("requests", 0),
            "p50_ms": search.get("p50_ms"),
            "p95_ms": search.get("p95_ms"),
        },
        "ingestion": {
            **report,
            "pages_per_document": PAGES,
            "uploads_accepted": knowledge["requests"].get("upload", {}).get("requests", 0),
            "uploads_refused_429": knowledge["requests"]
            .get("rejected:upload", {})
            .get("requests", 0),
        },
        "chat_with_search": {
            "chat_users": alone["users"],
            "search_users": beside["users"] - alone["users"],
            "chat_runs_alone": alone["runs"],
            "chat_runs_beside_search": beside["runs"],
            "chat_run_p95_ms_alone": before,
            "chat_run_p95_ms_beside_search": after,
            "chat_run_p95_change": round((after - before) / before, 3) if before else None,
            "search_p95_ms_beside_chat": beside["requests"].get("search", {}).get("p95_ms"),
        },
    }


def _memory_gb() -> int | None:
    sysconf = getattr(os, "sysconf", None)
    if callable(sysconf):
        try:
            page_size = int(sysconf("SC_PAGE_SIZE"))
            phys_pages = int(sysconf("SC_PHYS_PAGES"))
            return int(round(page_size * phys_pages / 2**30))
        except (ValueError, OSError, AttributeError):
            return None
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="loadtest.knowledge")
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("baseline")
    build.add_argument("--steps", type=Path, required=True)
    build.add_argument("--image", required=True)
    build.add_argument("--note", default="")
    args = parser.parse_args(argv)
    print(json.dumps(baseline(args.steps, args.image, args.note), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
