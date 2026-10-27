# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""A user's memories in a LangGraph `BaseStore`, one namespace per owner (ADR 0009 decision 7).

Namespace `("memories", owner_key)` where `owner_key` is the HMAC owner key, never a raw subject
or an ID the caller chose. No semantic search: a user's memories are few and short, so they are
listed whole. The ID of a memory is an HMAC of the owner and the normalised text under a server
secret, so remembering the same thing twice is one memory, yet an ID (which appears in logs and
audit events) is neither a plain hash of what the user wrote nor comparable between users.
Limits (count, length, age) are the operator's and apply per user.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from langgraph.store.base import BaseStore

from neuron_agent.config.settings import Settings
from neuron_agent.errors.base import MemoryFullError
from neuron_agent.observability import metrics, semconv, telemetry
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


_Memories = list[Memory]


class MemoryStore:
    """Per-user memory with the operator's limits. All methods take the owner key."""

    def __init__(
        self,
        store: BaseStore,
        *,
        id_key: bytes,
        max_items: int,
        max_chars: int,
        ttl_days: int | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store = store
        self._id_key = id_key
        self._max_items = max_items
        self._max_chars = max_chars
        self._ttl = timedelta(days=ttl_days) if ttl_days else None
        self._clock = clock

    @contextmanager
    def _traced(self, operation: str) -> Iterator[dict[str, int]]:
        """A span and a count for one operation: its name, outcome and item count only."""
        result: dict[str, int] = {}
        outcome = "error"
        with telemetry.start_span(
            f"{semconv.MEMORY_SPAN_PREFIX}.{operation}",
            attributes={semconv.NEURON_MEMORY_OPERATION: operation},
        ) as span:
            try:
                yield result
                outcome = "success"
            finally:
                span.set_attribute(semconv.NEURON_OUTCOME, outcome)
                if "items" in result:
                    span.set_attribute(semconv.NEURON_MEMORY_ITEMS, result["items"])
                metrics.record_memory_operation(operation, outcome=outcome)

    @staticmethod
    def _namespace(owner_key: str | None) -> tuple[str, str]:
        return (_ROOT, owner_key or "anonymous")

    def memory_id(self, owner_key: str | None, text: str) -> str:
        """The ID `remember` gives `text` for this owner: stable, so a repeat is the same memory."""
        message = f"{owner_key or 'anonymous'}\0{' '.join(text.split()).casefold()}"
        return hmac.new(self._id_key, message.encode(), hashlib.sha256).hexdigest()[:32]

    async def remember(self, owner_key: str | None, text: str) -> Memory:
        """Store `text`, or return the memory that already says it. Raises on bad input or a
        full memory; the text passes the same policy as a user message."""
        clean = validate_user_message(text, max_chars=self._max_chars)
        with self._traced("remember") as result:
            key = self.memory_id(owner_key, clean)
            namespace = self._namespace(owner_key)
            existing = await self._store.aget(namespace, key)
            if existing is not None and not self._expired(existing.value):
                memory = _memory(key, existing.value)
            else:
                current = await self._all(owner_key)
                if len(current) >= self._max_items:
                    raise MemoryFullError("the memory is full")
                value = {"text": clean, "created_at": self._clock().isoformat()}
                await self._store.aput(namespace, key, value)
                memory = _memory(key, value)
                result["items"] = len(current) + 1
            return memory

    async def list(self, owner_key: str | None) -> _Memories:
        """The user's memories, oldest first. Expired ones are removed as they are found."""
        with self._traced("list") as result:
            found = await self._all(owner_key)
            result["items"] = len(found)
            return found

    async def _all(self, owner_key: str | None) -> _Memories:
        namespace = self._namespace(owner_key)
        found: _Memories = []
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
        with self._traced("forget"):
            namespace = self._namespace(owner_key)
            if await self._store.aget(namespace, memory_id) is None:
                return False
            await self._store.adelete(namespace, memory_id)
            return True

    async def erase(self, owner_key: str | None) -> int:
        """Delete all of the user's memories; returns how many."""
        with self._traced("erase") as result:
            namespace = self._namespace(owner_key)
            removed = 0
            for _ in range(_MAX_PAGES):
                items = await self._store.asearch(namespace, limit=_PAGE)
                for item in items:
                    await self._store.adelete(namespace, item.key)
                removed += len(items)
                if len(items) < _PAGE:
                    break
            result["items"] = removed
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
            await self._all(namespace[1])
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


def memory_id_key(settings: Settings) -> bytes:
    """The secret memory IDs are keyed with: the identity key (staging and production require
    one). Development without authentication has none and no real users, so it gets a fixed one."""
    key = settings.identity_hash_key
    return (key.get_secret_value() if key else "neuron-development-memory").encode()
