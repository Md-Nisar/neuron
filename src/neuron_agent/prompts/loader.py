"""Prompt file loader."""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import files


@lru_cache
def load_prompt(relative_path: str) -> str:
    """Load a packaged prompt by relative path."""
    prompt = files("neuron_agent.prompts").joinpath(relative_path).read_text(encoding="utf-8")
    return prompt.strip()
