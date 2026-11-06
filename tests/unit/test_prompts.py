"""The system prompt is versioned (RAG-04.03): changing it without a version bump fails here."""

from __future__ import annotations

import hashlib

from neuron_agent.prompts.loader import SYSTEM_PROMPT_VERSION, load_prompt

# Update both together, and record the new version in CHANGELOG.md.
_PINNED = (2, "0b628980c767bc6c8ebc218f854c24773474aa645ad1c339f397382710eef47f")


def test_the_system_prompt_version_matches_its_content() -> None:
    # The text the model gets: read in text mode, so a CRLF checkout (Windows) hashes the same.
    text = load_prompt("system/main.md")
    assert (SYSTEM_PROMPT_VERSION, hashlib.sha256(text.encode()).hexdigest()) == _PINNED


def test_the_prompt_asks_for_abstention_when_knowledge_has_no_answer() -> None:
    prompt = load_prompt("system/main.md")
    assert "`no_relevant_results`" in prompt
    assert "their documents have nothing on it" in prompt
