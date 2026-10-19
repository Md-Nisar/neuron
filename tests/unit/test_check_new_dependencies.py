"""New-dependency gate for AI-assisted changes (`scripts/check_new_dependencies.py`)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from scripts import check_new_dependencies as check

NOW = datetime(2026, 10, 18, tzinfo=UTC)


def _metadata(first_upload: datetime, releases: int = 3) -> dict[str, Any]:
    stamp = first_upload.isoformat().replace("+00:00", "Z")
    files = [{"upload_time_iso_8601": stamp}]
    return {
        "info": {"summary": "A package"},
        "releases": {f"1.{i}": files for i in range(releases)},
    }


def test_declared_packages_reads_every_requirement_list_and_normalizes() -> None:
    pyproject = {
        "project": {
            "name": "neuron-agent",
            "dependencies": ["FastAPI>=0.1", "psycopg[binary,pool]>=3.2"],
            "optional-dependencies": {"eval": ["langsmith>=0.5"]},
        },
        "dependency-groups": {"dev": ["Py_Test>=9", {"include-group": "lint"}]},
    }

    assert check.declared_packages(pyproject) == {"fastapi", "psycopg", "langsmith", "py-test"}


def test_declared_packages_ignores_the_project_itself() -> None:
    pyproject = {
        "project": {
            "name": "neuron_agent",
            "optional-dependencies": {"all": ["neuron-agent[eval]"]},
        }
    }

    assert check.declared_packages(pyproject) == set()


def test_missing_package_fails_as_possible_hallucination() -> None:
    verdict = check.judge("fastapi-auth-helperz", None, NOW, allow_young=False)

    assert not verdict.ok
    assert "hallucinated" in verdict.message


def test_young_package_fails_unless_approved() -> None:
    metadata = _metadata(NOW - timedelta(days=10))

    assert not check.judge("newpkg", metadata, NOW, allow_young=False).ok
    assert check.judge("newpkg", metadata, NOW, allow_young=True).ok


def test_established_package_passes() -> None:
    verdict = check.judge(
        "requests", _metadata(NOW - timedelta(days=4000), releases=150), NOW, False
    )

    assert verdict.ok
    assert "150 releases" in verdict.message


def test_package_without_files_fails() -> None:
    assert not check.judge("empty", {"info": {}, "releases": {"1.0": []}}, NOW, False).ok
