"""New npm dependency gate (`scripts/check_new_npm_dependencies.py`)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from scripts import check_new_npm_dependencies as check

NOW = datetime(2026, 10, 28, tzinfo=UTC)


def _document(created: datetime | None, versions: int = 3) -> dict[str, Any]:
    time = {} if created is None else {"created": created.isoformat().replace("+00:00", "Z")}
    return {"time": time, "versions": {f"1.{i}.0": {} for i in range(versions)}}


def test_declared_packages_reads_every_dependency_section() -> None:
    manifest = {
        "name": "neuron-web",
        "dependencies": {"react": "19.3.1"},
        "devDependencies": {"@types/react": "19.3.0"},
        "optionalDependencies": {"fsevents": "2.3.3"},
        "peerDependencies": {"react-dom": "19.3.1"},
        "scripts": {"lint": "eslint ."},
    }

    assert check.declared_packages(manifest) == {
        "react",
        "@types/react",
        "fsevents",
        "react-dom",
    }


def test_unknown_package_is_refused_as_possibly_hallucinated() -> None:
    verdict = check.judge("reakt-dom", None, NOW, allow_young=False)

    assert not verdict.ok
    assert "hallucinated" in verdict.message


def test_young_package_is_refused_unless_a_human_approved_it() -> None:
    young = _document(NOW - timedelta(days=check.MIN_AGE_DAYS - 1))

    assert not check.judge("fresh", young, NOW, allow_young=False).ok
    assert check.judge("fresh", young, NOW, allow_young=True).ok


def test_package_at_the_age_limit_passes() -> None:
    assert check.judge("steady", _document(NOW - timedelta(days=check.MIN_AGE_DAYS)), NOW, False).ok


def test_document_without_a_creation_time_is_refused() -> None:
    assert not check.judge("odd", _document(None), NOW, allow_young=True).ok


@pytest.mark.parametrize("name", ["../etc/passwd", "Upper", "a b", "@scope", "react?x=1", ""])
def test_malformed_names_never_reach_the_registry(name: str) -> None:
    with pytest.raises(ValueError, match="not a valid npm package name"):
        check.fetch_metadata(name)


def test_a_missing_base_manifest_counts_as_empty(tmp_path: Path) -> None:
    head = tmp_path / "package.json"
    head.write_text(json.dumps({"dependencies": {"react": "19.3.1"}}), encoding="utf-8")

    assert check.declared_packages(check._load(str(tmp_path / "absent.json"))) == set()
    assert check.declared_packages(check._load(str(head))) == {"react"}


def test_no_added_packages_passes_without_network(tmp_path: Path) -> None:
    manifest = tmp_path / "package.json"
    manifest.write_text(json.dumps({"dependencies": {"react": "19.3.1"}}), encoding="utf-8")

    assert check.main(["check", str(manifest), str(manifest)]) == 0
