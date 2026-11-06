# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Prompt file loader."""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import files

# Bumped with every change to `system/main.md`; a test pins it to the file's hash. Recorded in
# the changelog and in eval reports, so a quality change can be traced to the prompt.
SYSTEM_PROMPT_VERSION = 2


@lru_cache
def load_prompt(relative_path: str) -> str:
    """Load a packaged prompt by relative path."""
    prompt = files("neuron_agent.prompts").joinpath(relative_path).read_text(encoding="utf-8")
    return prompt.strip()
