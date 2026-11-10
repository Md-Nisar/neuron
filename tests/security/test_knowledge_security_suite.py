"""The knowledge security suite: the twelve cases of the v1.1.0 security gate (RAG-08.02, #503).

One list names each case and the tests that prove it. This file checks, in `make test`, that every
named test exists and will run: tests outside `tests/integration` are collected by `make test`;
those inside it need Postgres with pgvector and carry the `postgres` marker, so CI's
`postgres-integration` job runs them and fails on any skip (`scripts/require_postgres_tests.py`).
The threat model's "Knowledge Engine" table lists the same twelve cases.
"""

from __future__ import annotations

import ast
import re
from functools import cache
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[2]
_MAKE_TEST = ("tests/unit/", "tests/graph/", "tests/security/", "tests/resilience/", "tests/e2e/")
_API = "tests/integration/test_postgres_knowledge_api.py"
_SEARCH = "tests/integration/test_postgres_knowledge_search.py"
_DOWNLOAD = "tests/integration/test_postgres_knowledge_download.py"
_PURGE = "tests/integration/test_postgres_knowledge_purge.py"
_INGEST = "tests/integration/test_postgres_knowledge_ingest.py"
_INJECTION = "tests/security/test_knowledge_injection.py"
_CITATIONS = "tests/security/test_citations.py"
_PARSING = "tests/unit/test_knowledge_parsing.py"
_PROVIDERS = "tests/unit/test_knowledge_providers.py"

# Case -> the tests that fail when its control is removed ("path::function").
SUITE: dict[str, list[str]] = {
    "Foreign kb_id or doc_id": [
        f"{_API}::test_the_matrix_covers_every_knowledge_route",
        f"{_API}::test_another_users_base_is_the_same_404_as_an_unknown_id",
    ],
    "Same text in two users' bases": [
        f"{_SEARCH}::test_each_user_sees_only_their_own_chunk",
        "tests/integration/test_postgres_knowledge_tables.py"
        "::test_the_app_role_sees_only_the_knowledge_bases_it_sets",
    ],
    "Access revoked while a citation is open": [
        f"{_DOWNLOAD}::test_a_chunk_comes_with_its_neighbours_and_access_is_rechecked_each_time",
    ],
    "Delete during purge": [
        f"{_PURGE}::test_a_deleted_documents_chunks_are_unreachable_until_purged",
        f"{_PURGE}::test_a_purge_stopped_half_way_completes_on_retry",
        f"{_PURGE}::test_an_upload_committing_during_the_base_delete_is_tombstoned_with_it",
    ],
    "Instructions hidden in a document": [
        f"{_INJECTION}::test_every_injection_case_of_the_dataset_is_played_here",
        f"{_INJECTION}::test_the_planted_instruction_reaches_the_model_only_as_framed_data",
        f"{_INJECTION}::test_a_hidden_pdf_instruction_to_forget_waits_for_the_user",
        f"{_INJECTION}::test_a_table_cell_instruction_saves_no_note",
    ],
    "Fake or planted cite_id": [
        f"{_CITATIONS}::test_a_cite_id_no_tool_returned_is_dropped_and_counted",
        f"{_CITATIONS}::test_a_cite_id_copied_from_a_passage_is_dropped",
        f"{_INJECTION}::test_planted_cite_ids_are_dropped_and_a_minted_one_is_kept",
    ],
    "Exfiltration to MCP after a search": [
        "tests/security/test_knowledge_tools.py"
        "::test_after_a_search_an_outbound_tool_needs_approval",
        f"{_INJECTION}::test_an_alt_text_instruction_cannot_send_the_conversation_out",
    ],
    "Worker killed during ingestion": [
        "tests/integration/test_postgres_knowledge_worker.py"
        "::test_a_killed_workers_job_is_retried_and_completes_once",
        f"{_INGEST}::test_a_crash_before_commit_then_a_retry_equals_a_clean_run",
    ],
    "HTML or SVG download": [
        f"{_DOWNLOAD}::test_the_original_downloads_as_an_attachment_never_rendered",
    ],
    "Zip bomb, page bomb, encrypted or macro file": [
        f"{_PARSING}::test_a_zip_bomb_is_refused_by_its_inflated_size",
        f"{_PARSING}::test_page_and_block_bombs_are_refused",
        f"{_PARSING}::test_unsafe_or_mislabelled_files_are_refused_before_parsing",
        "tests/unit/test_knowledge_docling_serve.py::test_a_document_past_the_page_cap_is_refused",
        "tests/unit/test_reference_stack.py::test_the_parser_has_no_route_out",
    ],
    "Erase everything": [
        "tests/integration/test_postgres_knowledge_erase.py"
        "::test_after_the_purge_nothing_of_the_owner_remains_and_only_then_complete",
        "tests/unit/test_thread_lifecycle.py"
        "::test_erase_everything_is_complete_only_once_the_knowledge_purge_is_done",
    ],
    "Hosted provider under a self-hosted policy": [
        f"{_PROVIDERS}::test_self_hosted_only_refuses_nvidia_at_startup",
        f"{_PROVIDERS}::test_processing_locality_check",
        f"{_INGEST}::test_a_self_hosted_base_is_never_sent_to_a_hosted_provider",
        f"{_SEARCH}::test_a_base_kept_off_hosted_processing_is_searched_by_text_only",
    ],
}
_NODES = sorted({node for nodes in SUITE.values() for node in nodes})


@cache
def _module(path: str) -> ast.Module:
    return ast.parse((_ROOT / path).read_text(encoding="utf-8"))


def _tests(path: str) -> set[str]:
    return {
        n.name
        for n in _module(path).body
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) and n.name.startswith("test_")
    }


def _threat_model_cases() -> list[str]:
    text = (_ROOT / "docs/security/threat-model.md").read_text(encoding="utf-8")
    section = text.split("## Knowledge Engine (v1.1.0)", 1)[1].split("\n## ", 1)[0]
    rows = [line for line in section.splitlines() if line.startswith("| ")]
    return [row.split("|")[1].strip().replace("`", "") for row in rows[2:]]  # no header rows


def test_the_suite_has_the_twelve_cases_of_the_threat_model() -> None:
    assert len(SUITE) == 12
    cases = _threat_model_cases()
    assert len(cases) == 12
    for case, row in zip(SUITE, cases, strict=True):
        assert row.startswith(case), (case, row)


@pytest.mark.parametrize("node", _NODES)
def test_every_named_test_exists(node: str) -> None:
    path, name = node.split("::")
    assert (_ROOT / path).is_file(), path
    assert name in _tests(path), node


@pytest.mark.parametrize("node", _NODES)
def test_every_named_test_runs_in_make_test_or_the_postgres_job(node: str) -> None:
    path = node.split("::")[0]
    if path.startswith("tests/integration/"):
        source = (_ROOT / path).read_text(encoding="utf-8")
        marks = re.search(r"^pytestmark = \[(.*)\]$", source, re.MULTILINE)
        assert marks and "pytest.mark.postgres" in marks.group(1), path
    else:
        assert path.startswith(_MAKE_TEST), path


def test_the_threat_model_names_only_test_files_that_exist() -> None:
    text = (_ROOT / "docs/security/threat-model.md").read_text(encoding="utf-8")
    section = text.split("## Knowledge Engine (v1.1.0)", 1)[1].split("\n## ", 1)[0]
    named = set(re.findall(r"`(test_[a-z0-9_]+\.py)`", section))
    present = {p.name for p in (_ROOT / "tests").rglob("test_*.py")}
    assert named and named <= present, named - present
    assert all(Path(node.split("::")[0]).name in named for node in _NODES)
