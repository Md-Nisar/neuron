# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""A user's memories in a LangGraph `BaseStore`, one namespace per owner (ADR 0009 decision 7).

Namespace `("memories", owner_key)` where `owner_key` is the HMAC owner key, never a raw subject
or an ID the caller chose. No semantic search: a user's memories are few and short, so they are
listed whole. The key of a memory is a hash of its normalised text, so remembering the same
thing twice is one memory. Limits (count, length, age) are the operator's and apply per user.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from langgraph.store.base import BaseStore

from neuron_agent.errors.base import MemoryFullError
from neuron_agent.security.input_policy import validate_user_message

_ROOT = "memories"
_PAGE = 100
# More than any limit allows; a namespace this large is a bug or an attack, not a user.
_MAX_PAGES = 12


@dataclass(frozen=True)
class Memory:
    """One remembered fact: its stable ID, the user's words, and when it was stored."""

    id: str
    text: str
    created_at: datetime


class MemoryStore:
    """Per-user memory with the operator's limits. All methods take the owner key."""

    def __init__(
        self,
        store: BaseStore,
        *,
        max_items: int,
        max_chars: int,
        ttl_days: int | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store = store
        self._max_items = max_items
        self._max_chars = max_chars
        self._ttl = timedelta(days=ttl_days) if ttl_days else None
        self._clock = clock

    @staticmethod
    def _namespace(owner_key: str | None) -> tuple[str, str]:
        return (_ROOT, owner_key or "anonymous")

    async def remember(self, owner_key: str | None, text: str) -> Memory:
        """Store `text`, or return the memory that already says it. Raises on bad input or a
        full memory; the text passes the same policy as a user message."""
        clean = validate_user_message(text, max_chars=self._max_chars)
        key = hashlib.sha256(" ".join(clean.split()).casefold().encode()).hexdigest()[:32]
        namespace = self._namespace(owner_key)
        existing = await self._store.aget(namespace, key)
        if existing is not None and not self._expired(existing.value):
            return _memory(key, existing.value)
        if len(await self.list(owner_key)) >= self._max_items:
            raise MemoryFullError("the memory is full")
        value = {"text": clean, "created_at": self._clock().isoformat()}
        await self._store.aput(namespace, key, value)
        return _memory(key, value)

    async def list(self, owner_key: str | None) -> list[Memory]:
        """The user's memories, oldest first. Expired ones are removed as they are found."""
        namespace = self._namespace(owner_key)
        found: list[Memory] = []
        for page in range(_MAX_PAGES):
            items = await self._store.asearch(namespace, limit=_PAGE, offset=page * _PAGE)
            for item in items:
                if self._expired(item.value):
                    await self._store.adelete(namespace, item.key)
                else:
                    found.append(_memory(item.key, item.value))
            if len(items) < _PAGE:
                break
        return sorted(found, key=lambda memory: memory.created_at)

    async def forget(self, owner_key: str | None, memory_id: str) -> bool:
        """Delete one of the user's memories; False if they have none with this ID."""
        namespace = self._namespace(owner_key)
        if await self._store.aget(namespace, memory_id) is None:
            return False
        await self._store.adelete(namespace, memory_id)
        return True

    async def erase(self, owner_key: str | None) -> int:
        """Delete all of the user's memories; returns how many."""
        namespace = self._namespace(owner_key)
        removed = 0
        for _ in range(_MAX_PAGES):
            items = await self._store.asearch(namespace, limit=_PAGE)
            for item in items:
                await self._store.adelete(namespace, item.key)
            removed += len(items)
            if len(items) < _PAGE:
                break
        return removed

    async def purge_expired(self) -> int:
        """Delete every user's expired memories (the operator's retention job); returns how many.

        Without this a user who never comes back would keep theirs: expiry otherwise happens when
        their owner key next lists or adds. Does nothing without a TTL.
        """
        if self._ttl is None:
            return 0
        removed = 0
        for namespace in await self._store.alist_namespaces(prefix=(_ROOT,), max_depth=2):
            before = len(await self._store.asearch(namespace, limit=_PAGE))
            await self.list(namespace[1])
            removed += before - len(await self._store.asearch(namespace, limit=_PAGE))
        return removed

    def _expired(self, value: Mapping[str, object]) -> bool:
        if self._ttl is None:
            return False
        return self._clock() - datetime.fromisoformat(str(value["created_at"])) >= self._ttl


def _memory(key: str, value: Mapping[str, object]) -> Memory:
    return Memory(
        id=key, text=str(value["text"]), created_at=datetime.fromisoformat(str(value["created_at"]))
    )
