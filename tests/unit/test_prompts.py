"""The system prompt is versioned (RAG-04.03): changing it without a version bump fails here."""

from __future__ import annotations

import hashlib
from importlib.resources import files

from neuron_agent.prompts.loader import SYSTEM_PROMPT_VERSION, load_prompt

# Update both together, and record the new version in CHANGELOG.md.
_PINNED = (2, "1a4006c1ade7de5996c190290ebdccc8ef78835d6dd1d9dedd692d9407d9c224")


def test_the_system_prompt_version_matches_its_content() -> None:
    data = files("neuron_agent.prompts").joinpath("system/main.md").read_bytes()
    assert (SYSTEM_PROMPT_VERSION, hashlib.sha256(data).hexdigest()) == _PINNED


def test_the_prompt_asks_for_abstention_when_knowledge_has_no_answer() -> None:
    prompt = load_prompt("system/main.md")
    assert "`no_relevant_results`" in prompt
    assert "their documents have nothing on it" in prompt
