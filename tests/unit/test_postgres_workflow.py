from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

_FILE = Path(".github/workflows/postgres-integration.yml")
_PIN = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")


def _job() -> dict[str, Any]:
    workflow = yaml.safe_load(_FILE.read_text("utf-8"))
    assert workflow["permissions"] == {"contents": "read"}
    job: dict[str, Any] = workflow["jobs"]["postgres-integration"]
    return job


def test_push_is_limited_to_main() -> None:
    workflow = yaml.safe_load(_FILE.read_text("utf-8"))
    assert workflow[True]["push"] == {"branches": ["main"]}  # PRs run via pull_request only
    assert "pull_request" in workflow[True]


def test_postgres_job_guards() -> None:
    job = _job()
    assert job["runs-on"] == "ubuntu-latest"
    assert 0 < job["timeout-minutes"] <= 30
    image = job["services"]["postgres"]["image"]
    assert re.fullmatch(r"postgres:16@sha256:[0-9a-f]{64}", image)
    assert job["env"]["APP_TEST_POSTGRES_DSN"].startswith("postgresql://")
    assert "secrets." not in _FILE.read_text("utf-8")  # no provider key reaches the job
    runs = "\n".join(s.get("run", "") for s in job["steps"])
    assert "OPENAI_API_KEY" in runs  # fails when a provider key is present
    assert "pytest -m postgres" in runs  # live-model tests carry no postgres marker
    assert "--junitxml" in runs
    assert "scripts/require_postgres_tests.py" in runs


def test_postgres_job_actions_are_sha_pinned() -> None:
    uses = [s["uses"] for s in _job()["steps"] if "uses" in s]
    assert uses
    for ref in uses:
        assert _PIN.match(ref), ref


def test_postgres_marker_is_registered_and_applied() -> None:
    assert '"postgres:' in Path("pyproject.toml").read_text("utf-8")
    source = Path("tests/integration/test_postgres_checkpointer.py").read_text("utf-8")
    assert "pytest.mark.postgres" in source


def _report(tmp_path: Path, xml: str) -> Path:
    path = tmp_path / "junit.xml"
    path.write_text(xml, "utf-8")
    return path


def test_junit_check_requires_executed_tests(tmp_path: Path) -> None:
    from scripts.require_postgres_tests import check

    suite = '<testsuite tests="{t}" skipped="{s}" failures="0"/>'
    for wrap in ("{}", "<testsuites>{}</testsuites>"):
        ran = _report(tmp_path, wrap.format(suite.format(t=5, s=0)))
        assert check(ran) is None
        assert check(_report(tmp_path, wrap.format(suite.format(t=0, s=0)))) is not None
        assert check(_report(tmp_path, wrap.format(suite.format(t=5, s=1)))) is not None


def test_junit_check_main_exit_codes(tmp_path: Path) -> None:
    from scripts.require_postgres_tests import main

    ok = _report(tmp_path, '<testsuites><testsuite tests="5" skipped="0"/></testsuites>')
    assert main(["x", str(ok)]) == 0
    bad = _report(tmp_path, '<testsuite tests="5" skipped="5"/>')
    assert main(["x", str(bad)]) == 1
