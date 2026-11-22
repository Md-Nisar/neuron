"""Scope-safe value lookup, trace redaction and router calibration."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Iterable, Sequence


# ---------- scope-partitioned value index -------------------------------------------------
def scope_key(row_filters: dict[str, Sequence[str]]) -> str:
    """Stable key for a security scope (e.g. {'region': ['APAC']}). Values indexed under one
    scope are only ever served to principals whose row filters produce the same key."""
    canon = "|".join(f"{k}={','.join(sorted(v))}" for k, v in sorted(row_filters.items()))
    return hashlib.sha256(canon.encode()).hexdigest()[:16]


@dataclass(frozen=True)
class ValueEntry:
    table: str
    column: str
    value: str
    scope: str            # scope_key, or "public" for non-sensitive low-cardinality columns


class ScopedValueIndex:
    """In-memory stand-in for the pgvector/tsvector value table. Production: a column
    `scope text NOT NULL` with RLS on the index table itself, same predicate as below."""

    def __init__(self, entries: Iterable[ValueEntry]):
        self._entries = list(entries)

    def lookup(self, text: str, principal_scope: str, readable_tables: set[str], k: int = 5):
        t = text.lower()
        hits = [e for e in self._entries
                if e.table in readable_tables
                and e.scope in ("public", principal_scope)
                and t in e.value.lower()]
        return hits[:k]


# ---------- trace redaction ----------------------------------------------------------------
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_DIGITS = re.compile(r"\b\d{9,19}\b")      # account, card, phone-like runs


def redact_trace(payload: dict, keep_result_rows: bool = False) -> dict:
    """Applied before any span leaves the process. Result rows are replaced by shape metadata
    unless the trace store is approved for production data."""
    out = {}
    for k, v in payload.items():
        if k in ("result_rows", "sample_values") and not keep_result_rows:
            out[k] = {"redacted": True, "count": len(v) if hasattr(v, "__len__") else None}
        elif isinstance(v, str):
            out[k] = _DIGITS.sub("[NUM]", _EMAIL.sub("[EMAIL]", v))
        elif isinstance(v, dict):
            out[k] = redact_trace(v, keep_result_rows)
        else:
            out[k] = v
    return out


# ---------- router calibration -------------------------------------------------------------
def choose_threshold(scored: Sequence[tuple[float, bool]], max_wrong_rate: float = 0.01,
                     min_support: int = 30) -> tuple[float | None, float, float]:
    """scored = [(router_score, answer_was_correct)] from the golden set for ONE tier.
    Return the lowest threshold whose accepted set has wrong-rate <= max_wrong_rate,
    maximising coverage. Returns (threshold, coverage, wrong_rate)."""
    best = (None, 0.0, 1.0)
    n = len(scored)
    for thr in sorted({s for s, _ in scored}):
        acc = [c for s, c in scored if s >= thr]
        if len(acc) < min_support:
            continue
        wrong = 1 - sum(acc) / len(acc)
        cov = len(acc) / n
        if wrong <= max_wrong_rate and cov > best[1]:
            best = (thr, cov, wrong)
    return best
