"""The knowledge eval corpus and security dataset (RAG-00.03) is valid and self-consistent.

The JSON schema checks the shape of each entry; `_integrity_errors` checks what a schema cannot:
references between cases and documents, page ranges, ownership, and the checksums of the
documents stored in the repository. Public documents are stored as URL and checksum only and
are not downloaded here.
"""

from __future__ import annotations

import copy
import gzip
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import jsonschema
import pytest

_FIXTURES = Path("tests/fixtures")
_DATASET = _FIXTURES / "knowledge_cases.json"
_SCHEMA = _FIXTURES / "knowledge_cases.schema.json"
_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _load(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _sources(case: dict[str, Any]) -> list[dict[str, Any]]:
    return list(case.get("expected_sources", []))


def _integrity_errors(dataset: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    documents = {doc["id"]: doc for doc in dataset["documents"]}
    for name, ids in (
        ("document", [doc["id"] for doc in dataset["documents"]]),
        ("case", [case["id"] for case in dataset["cases"]]),
    ):
        errors += [f"duplicate {name} id {i}" for i, n in Counter(ids).items() if n > 1]

    for doc in dataset["documents"]:
        if "path" in doc["source"]:
            path = _FIXTURES / doc["source"]["path"]
            if not path.is_file():
                errors.append(f"{doc['id']}: missing file {path}")
                continue
            content = path.read_bytes()
            if hashlib.sha256(content).hexdigest() != doc["sha256"]:
                errors.append(f"{doc['id']}: sha256 does not match {path}")
            if len(content) != doc["size_bytes"]:
                errors.append(f"{doc['id']}: size_bytes does not match {path}")
        if doc["media_type"] == "application/pdf" and "page_count" not in doc:
            errors.append(f"{doc['id']}: a PDF needs page_count")
        if "injection" in doc["classes"] and "path" not in doc["source"]:
            errors.append(f"{doc['id']}: injection documents must be stored in the repository")

    for case in dataset["cases"]:
        cid = case["id"]
        referenced = [s["document"] for s in _sources(case)]
        referenced += case.get("forbidden_documents", [])
        referenced += [case["document"]] if "document" in case else []
        missing = [d for d in referenced if d not in documents]
        errors += [f"{cid}: unknown document {d}" for d in missing]
        if missing:
            continue
        for source in _sources(case):
            doc = documents[source["document"]]
            if doc["owner"] != case["as_user"]:
                errors.append(f"{cid}: {doc['id']} is not owned by {case['as_user']}")
            if "pages" in source:
                if "page_count" not in doc:
                    errors.append(f"{cid}: {doc['id']} has no pages; cite a section")
                elif max(source["pages"]) > doc["page_count"]:
                    errors.append(f"{cid}: page beyond {doc['id']}'s {doc['page_count']} pages")
            elif "page_count" in doc:
                errors.append(f"{cid}: {doc['id']} is paginated; cite pages")
        for forbidden in case.get("forbidden_documents", []):
            if documents[forbidden]["owner"] == case["as_user"]:
                errors.append(f"{cid}: {forbidden} is owned by {case['as_user']} itself")
        if case["category"] == "injection":
            doc = documents[case["document"]]
            if "injection" not in doc["classes"] or doc["owner"] != case["as_user"]:
                errors.append(f"{cid}: {doc['id']} is not an injection document of the user")
    return errors


@pytest.fixture(scope="module")
def dataset() -> dict[str, Any]:
    return _load(_DATASET)


def test_schema_is_valid_draft_2020_12() -> None:
    jsonschema.Draft202012Validator.check_schema(_load(_SCHEMA))


def test_every_case_validates_against_the_schema(dataset: dict[str, Any]) -> None:
    jsonschema.Draft202012Validator(_load(_SCHEMA)).validate(dataset)


def test_cases_reference_existing_documents_and_local_files_match(
    dataset: dict[str, Any],
) -> None:
    assert _integrity_errors(dataset) == []


def test_minimum_case_counts(dataset: dict[str, Any]) -> None:
    counts = Counter(case["category"] for case in dataset["cases"])
    assert counts["answerable"] >= 50
    assert counts["unanswerable"] >= 10
    assert counts["acl"] >= 4
    assert counts["injection"] >= 4


def test_corpus_covers_the_required_formats_and_attacks(dataset: dict[str, Any]) -> None:
    documents = dataset["documents"]
    assert 30 <= len(documents) <= 100
    assert {"application/pdf", _DOCX, "text/markdown", "text/plain"} <= {
        d["media_type"] for d in documents
    }
    assert any("scanned" in d["classes"] for d in documents)
    assert any("tables" in d["classes"] for d in documents)
    attacks = {c["attack"] for c in dataset["cases"] if c["category"] == "injection"}
    assert attacks == {"hidden_text", "alt_text", "table_cell", "fake_cite_id"}
    users = {c["as_user"] for c in dataset["cases"] if c["category"] == "acl"}
    assert users == set(dataset["users"])


def test_every_document_records_a_licence_and_where_it_comes_from(
    dataset: dict[str, Any],
) -> None:
    for doc in dataset["documents"]:
        assert doc["licence"].strip(), doc["id"]
        assert ("url" in doc["source"]) != ("path" in doc["source"]), doc["id"]


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        pytest.param(
            lambda d: d["cases"][0]["expected_sources"][0].update(document="no-such-doc"),
            "unknown document no-such-doc",
            id="dangling-document",
        ),
        pytest.param(
            lambda d: d["cases"][0]["expected_sources"][0].update(pages=[9999]),
            "page beyond",
            id="page-out-of-range",
        ),
        pytest.param(
            lambda d: next(doc for doc in d["documents"] if "path" in doc["source"]).update(
                sha256="0" * 64
            ),
            "sha256 does not match",
            id="tampered-local-file",
        ),
        pytest.param(
            lambda d: next(c for c in d["cases"] if c["category"] == "acl").update(
                as_user="user_a", forbidden_documents=["acl-user-a-falcon"]
            ),
            "is owned by user_a itself",
            id="acl-forbids-own-document",
        ),
    ],
)
def test_integrity_check_reports_broken_references(
    dataset: dict[str, Any], mutate: Any, expected: str
) -> None:
    broken = copy.deepcopy(dataset)
    mutate(broken)
    assert any(expected in error for error in _integrity_errors(broken))


def test_schema_rejects_an_answerable_case_without_a_source(dataset: dict[str, Any]) -> None:
    broken = copy.deepcopy(dataset)
    del broken["cases"][0]["expected_sources"]
    validator = jsonschema.Draft202012Validator(_load(_SCHEMA))
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(broken)


def _phrase_in(alias: str, text: str) -> bool:
    norm = re.sub(r"\s+", " ", alias).lower()
    return re.search(rf"(?<![a-z0-9]){re.escape(norm)}(?![a-z0-9])", text) is not None


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).lower().strip()


@pytest.fixture(scope="module")
def parsed() -> dict[str, Any]:
    """The parser output stored for the eval, per document: its blocks."""
    data = json.loads(gzip.decompress((_FIXTURES / "knowledge/eval/parsed.json.gz").read_bytes()))
    return dict(data["documents"])


def _text(parsed: dict[str, Any], source: dict[str, Any], page: int | None = None) -> str:
    blocks = parsed[source["document"]]["blocks"]
    return _norm(
        " ".join(b.get("text", "") for b in blocks if page is None or b.get("page") == page)
    )


def _grounding_errors(cases: list[dict[str, Any]], parsed: dict[str, Any]) -> list[str]:
    """Answerable cases whose facts or evidence are not in their expected sources: the first
    phrase of every fact must appear in an expected document, and the evidence on an expected
    page (or anywhere in a sectioned document)."""
    errors = []
    for case in cases:
        if case["category"] != "answerable":
            continue
        sources = case["expected_sources"]
        documents = " ".join(_text(parsed, s) for s in sources)
        errors += [
            f"{case['id']}: fact {fact['any'][0]!r}"
            for fact in case["expected_facts"]
            if not _phrase_in(fact["any"][0], documents)
        ]
        places = [_text(parsed, s, page) for s in sources for page in s.get("pages", [None])]
        if not any(_norm(case["evidence"]) in place for place in places):
            errors.append(f"{case['id']}: evidence")
    return errors


def test_every_expected_fact_is_in_an_expected_source(
    dataset: dict[str, Any], parsed: dict[str, Any]
) -> None:
    # The OCR text of the scanned log joins "litres per" into one word, so that one quote,
    # checked by hand when it was written, is not found as typed.
    assert _grounding_errors(dataset["cases"], parsed) == ["answerable-063: evidence"]


def test_case_ids_and_questions_do_not_repeat(dataset: dict[str, Any]) -> None:
    ids = [c["id"] for c in dataset["cases"]]
    assert len(ids) == len(set(ids))
    # ACL cases ask one question as two users on purpose; answer cases must not repeat.
    questions = [
        _norm(c["question"])
        for c in dataset["cases"]
        if c["category"] in {"answerable", "unanswerable"}
    ]
    assert len(questions) == len(set(questions))
