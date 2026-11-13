"""Text search per language: `simple` against each language's own configuration (RAG-09.08).

Each case of `tests/fixtures/knowledge/multilingual/cases.json` searches its language's six
passages with the text channel's own match and rank (`websearch_to_tsquery`, `ts_rank_cd`,
as `knowledge/retrieval.py` runs them), once with `simple` and once with the base language's
configuration. Its questions use other word forms than its passage, as people write. With
`APP_KNOWLEDGE_MULTILINGUAL_REPORT` set, the figures are written to that path; ADR 0014
records them.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import psycopg
import pytest

pytestmark = [pytest.mark.eval, pytest.mark.postgres]

CASES = Path("tests/fixtures/knowledge/multilingual/cases.json")
_DSN = os.environ.get("APP_TEST_POSTGRES_DSN")
_TOP = 5
_SEARCH = (
    "SELECT id FROM jsonb_each_text(%(passages)s) p(id, text)"
    " WHERE to_tsvector(%(cfg)s::regconfig, text)"
    " @@ websearch_to_tsquery(%(cfg)s::regconfig, %(q)s)"
    " ORDER BY ts_rank_cd(to_tsvector(%(cfg)s::regconfig, text),"
    " websearch_to_tsquery(%(cfg)s::regconfig, %(q)s)) DESC, id LIMIT %(n)s"
)


def _measure(conn: psycopg.Connection[Any], language: dict[str, Any], cfg: str) -> dict[str, float]:
    found, reciprocal = 0, 0.0
    for question, wanted in language["cases"]:
        params = {"passages": json.dumps(language["passages"]), "cfg": cfg, "q": question}
        ids = [row[0] for row in conn.execute(_SEARCH, params | {"n": _TOP})]
        if wanted in ids:
            found += 1
            reciprocal += 1 / (ids.index(wanted) + 1)
    n = len(language["cases"])
    return {"recall_at_5": round(found / n, 3), "mrr": round(reciprocal / n, 3)}


def test_a_language_configuration_finds_what_simple_misses() -> None:
    if not _DSN:
        pytest.skip("APP_TEST_POSTGRES_DSN is not set; see OPERATIONS.md for a local Postgres.")
    languages = json.loads(CASES.read_text(encoding="utf-8"))["languages"]
    with psycopg.connect(_DSN, autocommit=True) as conn:
        report = {
            name: {cfg: _measure(conn, language, cfg) for cfg in ("simple", name)}
            for name, language in languages.items()
        }
    if path := os.environ.get("APP_KNOWLEDGE_MULTILINGUAL_REPORT"):
        Path(path).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for name, figures in report.items():
        assert figures[name]["recall_at_5"] >= figures["simple"]["recall_at_5"], name
    assert sum(f[n]["recall_at_5"] for n, f in report.items()) > sum(
        f["simple"]["recall_at_5"] for f in report.values()
    )
