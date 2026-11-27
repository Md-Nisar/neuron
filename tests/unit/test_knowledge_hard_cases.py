"""The hard-question eval set (RAG-13.01) is valid and self-consistent.

The JSON schema checks the shape of each case; the tests below check what a schema cannot: the
counts per category, that every required source is a document holding its quote, the licences,
that a follow-up case carries its earlier turns, and that an unanswerable case's withheld
evidence is nowhere in the documents.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import jsonschema
import pytest

_DIR = Path("tests/fixtures/knowledge/hard")
_COUNTS = {
    "multi_hop": 15,
    "comparison": 12,
    "synthesis": 10,
    "follow_up": 15,
    "vocabulary_mismatch": 10,
    "unanswerable": 10,
}
# Which benchmark each category comes from (owner, 2026-11-27).
_SOURCE = {
    "multi_hop": "musique",
    "unanswerable": "musique",
    "comparison": "2wiki",
    "synthesis": "frames",
    "follow_up": "mtrag",
    "vocabulary_mismatch": "clapnq",
}


def _norm(text: str) -> str:
    return " ".join(text.split())


@pytest.fixture(scope="module")
def dataset() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((_DIR / "cases.json").read_text(encoding="utf-8"))
    return data


@pytest.fixture(scope="module")
def documents(dataset: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = gzip.decompress((_DIR / dataset["documents_file"]).read_bytes())
    assert hashlib.sha256(raw).hexdigest() == dataset["documents_sha256"]
    return {d["id"]: d for d in json.loads(raw)["documents"]}


def test_the_cases_match_the_schema(dataset: dict[str, Any]) -> None:
    schema = json.loads((_DIR / "cases.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(dataset, schema)


def test_each_category_has_its_count_and_benchmark(dataset: dict[str, Any]) -> None:
    cases = dataset["cases"]
    assert Counter(c["category"] for c in cases) == _COUNTS
    assert all(c["benchmark"]["source"] == _SOURCE[c["category"]] for c in cases)
    assert len({c["id"] for c in cases}) == len(cases)
    assert len({(c["benchmark"]["source"], c["benchmark"]["id"]) for c in cases}) == len(cases)


def test_every_required_source_is_a_document_holding_its_quote(
    dataset: dict[str, Any], documents: dict[str, dict[str, Any]]
) -> None:
    for case in dataset["cases"]:
        for source in case["required_sources"]:
            doc = documents.get(source["document"])
            assert doc is not None, (case["id"], source["document"])
            if source["evidence"] is not None:
                assert _norm(source["evidence"]) in _norm(doc["text"]), case["id"]


def test_answerable_categories_need_the_sources_their_category_names(
    dataset: dict[str, Any],
) -> None:
    least = {"multi_hop": 2, "comparison": 2, "synthesis": 3, "follow_up": 1}
    for case in dataset["cases"]:
        # A multi-hop question needs passages, which may share an article; the others, articles.
        key = ("document", "evidence") if case["category"] == "multi_hop" else ("document",)
        n = len({tuple(s[k] for k in key) for s in case["required_sources"]})
        if case["category"] == "unanswerable":
            assert n == 0 and case["answer"] is None, case["id"]
        else:
            assert n >= least.get(case["category"], 1), case["id"]
            assert case["answer"] is not None or case.get("reference_answer"), case["id"]


def test_a_follow_up_carries_its_earlier_turns(dataset: dict[str, Any]) -> None:
    for case in [c for c in dataset["cases"] if c["category"] == "follow_up"]:
        turns = case["turns"]
        assert turns[0]["role"] == "user" and turns[-1]["role"] == "assistant", case["id"]
        roles = [t["role"] for t in turns]
        assert all(a != b for a, b in zip(roles, roles[1:], strict=False)), case["id"]
        assert case["standalone"] != case["question"], case["id"]


def test_withheld_evidence_is_in_no_document(
    dataset: dict[str, Any], documents: dict[str, dict[str, Any]]
) -> None:
    corpus = "\n".join(_norm(d["text"]) for d in documents.values())
    for case in [c for c in dataset["cases"] if c["category"] == "unanswerable"]:
        assert all(_norm(w) not in corpus for w in case["withheld_evidence"]), case["id"]


def test_every_document_carries_its_licence_and_source(
    dataset: dict[str, Any], documents: dict[str, dict[str, Any]]
) -> None:
    assert set(dataset["benchmarks"]) == set(_SOURCE.values())
    for doc in documents.values():
        assert doc["licence"] == "CC BY-SA 4.0", doc["id"]
        assert doc["source"] in {"musique", "2wiki", "frames", "clapnq"}, doc["id"]
        assert doc["id"].startswith(f"{doc['source']}-"), doc["id"]
        if doc["source"] == "frames":
            assert doc["url"].startswith("https://en.wikipedia.org/wiki/"), doc["id"]
            assert isinstance(doc["revision"], int), doc["id"]
