"""One version source (#153) and the changelog section script."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from scripts import changelog_section

import neuron_agent
from neuron_agent.config.settings import Settings

ROOT = Path(__file__).parents[2]


def test_code_version_matches_pyproject() -> None:
    expected = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]

    assert neuron_agent.__version__ == expected
    assert Settings.model_fields["version"].default == expected


def test_changelog_section_for_0_5_0() -> None:
    section = changelog_section.extract_section((ROOT / "CHANGELOG.md").read_text(), "0.5.0")

    assert section is not None
    assert section.startswith('"Evaluation + Observability"')
    assert "Breaking changes:" in section
    assert "## " not in section
    assert "One version source" not in section  # the Unreleased entry is not included


def test_changelog_section_script_exit_codes(capsys: pytest.CaptureFixture[str]) -> None:
    assert changelog_section.main(["x", "0.5.0"]) == 0
    assert "Breaking changes:" in capsys.readouterr().out

    assert changelog_section.main(["x", "9.9.9"]) == 1
    assert "no CHANGELOG section" in capsys.readouterr().err
