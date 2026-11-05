# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Citations the server can vouch for (RAG-05.01, ADR 0014 K6).

The knowledge tools give each passage a fresh `cite_id` and keep what it stands for in the tool
message's artifact, which the model never sees. The model's answer lists `cite_id`s, and only
those a knowledge tool returned in this run are kept: an id the model made up, or copied from a
passage's text, matches no artifact.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from neuron_agent.schemas.agent import Citation, CitationFields

# Tool messages whose artifacts hold this run's `cite_id`s.
MINTING_TOOLS = ("search_knowledge", "get_document_excerpt")


def minted(messages: Sequence[Any]) -> dict[str, dict[str, Any]]:
    """The `cite_id`s minted in `messages`, each with the passage it stands for."""
    cited: dict[str, dict[str, Any]] = {}
    for message in messages:
        if (
            isinstance(message, ToolMessage)
            and message.name in MINTING_TOOLS
            and message.status != "error"
            and isinstance(message.artifact, dict)
        ):
            cited.update(message.artifact)
    return cited


def validate(
    cite_ids: Sequence[str], run_messages: Sequence[BaseMessage]
) -> tuple[list[Citation], int]:
    """The listed citations a knowledge tool returned in this run, resolved, in the order
    listed and without repeats; and how many listed ids were rejected."""
    known = minted(run_messages)
    kept: dict[str, Citation] = {}
    rejected = 0
    for cite_id in cite_ids:
        if cite_id in kept:
            continue
        ref = known.get(cite_id)
        if ref is None:
            rejected += 1
        else:
            kept[cite_id] = Citation(cite_id=cite_id, **ref)
    return list(kept.values()), rejected


def stamp(cited: Sequence[Citation], run_messages: Sequence[BaseMessage]) -> dict[str, Any]:
    """The citation fields stored on the run's answer: empty unless the run called a knowledge
    tool that mints ids, in which case `grounded` is whether any citation was kept."""
    searched = any(
        call["name"] in MINTING_TOOLS
        for message in run_messages
        if isinstance(message, AIMessage)
        for call in message.tool_calls
    )
    if not searched:
        return {}
    fields = CitationFields(citations=list(cited), citation_schema_version=1, grounded=bool(cited))
    return fields.model_dump(mode="json")
