# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""A developer's `.env` must not change what tests see."""

from __future__ import annotations

from pathlib import Path

import pytest

from neuron_agent.config.settings import Settings


def test_settings_in_tests_ignore_a_dotenv_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text("APP_MAX_AGENT_ITERATIONS=3\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("APP_MAX_AGENT_ITERATIONS", raising=False)

    assert Settings().max_agent_iterations == Settings.model_fields["max_agent_iterations"].default
