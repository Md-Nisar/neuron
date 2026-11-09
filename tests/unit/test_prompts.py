"""The system prompt is versioned (RAG-04.03): changing it without a version bump fails here."""

from __future__ import annotations

import hashlib

from neuron_agent.prompts.loader import SYSTEM_PROMPT_VERSION, load_prompt

# Update both together, and record the new version in CHANGELOG.md.
_PINNED = (4, "65637383f7bcb2736d4229a394953fd9a3fe714373c3280727586bbd2bdebfcf")


def test_the_system_prompt_version_matches_its_content() -> None:
    # The text the model gets: read in text mode, so a CRLF checkout (Windows) hashes the same.
    text = load_prompt("system/main.md")
    assert (SYSTEM_PROMPT_VERSION, hashlib.sha256(text.encode()).hexdigest()) == _PINNED


def test_the_prompt_asks_for_abstention_when_knowledge_has_no_answer() -> None:
    prompt = load_prompt("system/main.md")
    assert "`no_relevant_results`" in prompt
    assert "their documents have nothing on it" in prompt


def test_the_prompt_asks_to_search_first_cite_only_support_and_not_repeat() -> None:
    # Version 3, from RAG-08.01's live eval: answers from general knowledge without a search,
    # abstentions that cited what was read, and repeated searches up to the step limit.
    prompt = load_prompt("system/main.md")
    assert "search them before answering a factual question" in prompt
    assert "do not list passages you only read" in prompt
    assert "list no citations" in prompt
    assert "Do not repeat a knowledge search" in prompt


def test_the_prompt_asks_to_cite_nothing_for_a_false_premise() -> None:
    # Version 4, from RAG-08.01's second live run: asked about a phase 3 that does not exist, the
    # model said so but cited the plan's phases 1 and 2, so the answer was grounded.
    prompt = load_prompt("system/main.md")
    assert "something the documents do not mention" in prompt
    assert "set `not_in_documents` to true, even if you say what they do list" in prompt
