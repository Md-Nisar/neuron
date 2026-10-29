from __future__ import annotations

from pathlib import Path

from scripts import flow_report


def test_python_flows_are_read_from_the_flow_marker(tmp_path: Path) -> None:
    (tmp_path / "test_a.py").write_text(
        "import pytest\n"
        "@pytest.mark.flow('chat', 'resume')\n"
        "def test_one(): ...\n"
        "@pytest.mark.slow\n"
        "def test_two(): ...\n"
        "@pytest.mark.flow('chat')\n"
        "async def test_three(): ...\n"
    )
    assert flow_report.python_flows(tmp_path) == {
        "chat": ["test_one", "test_three"],
        "resume": ["test_one"],
    }


def test_the_report_lists_every_flow_and_names_the_gaps() -> None:
    table = flow_report.render({"chat": ["t"]}, {"chat": ["b"], "extra": ["x"]})
    assert "| chat | Send a message, stream the answer | 1 | 1 |" in table
    assert "| extra | (not in FLOWS) | - | 1 |" in table
    assert "Flows with no end-to-end test:" in table and "theme" in table


def test_the_report_says_when_browser_tests_could_not_be_listed() -> None:
    table = flow_report.render({}, None)
    assert "| chat | Send a message, stream the answer | - | n/a |" in table
    assert "could not be listed" in table


def test_the_script_never_fails_the_build(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(flow_report, "browser_flows", lambda _: None)
    assert flow_report.main() == 0
    assert "Flow" in capsys.readouterr().out
