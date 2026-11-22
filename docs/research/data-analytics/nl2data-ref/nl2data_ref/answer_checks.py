"""Runtime answer checks and evaluation helpers.

faithful(): every number in the answer text must be traceable to the result set or to a
value the composer computed in code (passed in `derived`). Otherwise the answer is
rejected and the system falls back to returning the table with a template sentence.

results_match(): result-set comparison for the golden-set harness: type-normalised,
float-tolerant, column-order-insensitive by name, row order optional.
"""
from __future__ import annotations

import datetime as dt
import math
import re
from collections import Counter
from decimal import Decimal
from typing import Iterable, Sequence

_NUM = re.compile(r"(?<![\w.])[-−]?\$?\d{1,3}(?:,\d{3})+(?:\.\d+)?%?|(?<![\w.])[-−]?\$?\d+(?:\.\d+)?%?")
_YEARISH = re.compile(r"^(19|20)\d\d$")


def _to_float(token: str) -> tuple[float, bool]:
    pct = token.endswith("%")
    t = token.replace("−", "-").replace("$", "").replace(",", "").rstrip("%")
    return float(t), pct


def numbers_in_text(text: str) -> list[tuple[float, bool, str]]:
    out = []
    for m in _NUM.finditer(text):
        tok = m.group(0)
        val, pct = _to_float(tok)
        out.append((val, pct, tok))
    return out


def _close(a: float, b: float, rel: float) -> bool:
    return math.isclose(a, b, rel_tol=rel, abs_tol=0.5 * 10 ** -2)


def faithful(text: str, rows: Iterable[Sequence], derived: Iterable[float] = (),
             rel: float = 0.005, ignore: Iterable[str] = ()) -> tuple[bool, list[str]]:
    """Return (ok, unsupported_tokens). Years and explicitly ignored tokens are skipped."""
    pool: list[float] = []
    for r in rows:
        for v in r:
            if isinstance(v, (int, float, Decimal)) and not isinstance(v, bool):
                pool.append(float(v))
    pool += [float(d) for d in derived]
    ignore = set(ignore)
    bad = []
    for val, pct, tok in numbers_in_text(text):
        if tok in ignore or (_YEARISH.match(tok) and not pct):
            continue
        cands = [val, val / 100.0] if pct else [val]
        if not any(_close(c, p, rel) or _close(round(p, 1), c, rel) for c in cands for p in pool):
            bad.append(tok)
    return (not bad, bad)


def _norm(v, rel_digits: int):
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float, Decimal)):
        f = float(v)
        if math.isnan(f):
            return "NaN"
        return float(f"{f:.{rel_digits}g}")
    if isinstance(v, dt.datetime):
        return v.replace(tzinfo=None).isoformat()
    if isinstance(v, dt.date):
        return v.isoformat()
    return str(v).strip()


def results_match(got_cols: Sequence[str], got_rows: Sequence[Sequence],
                  exp_cols: Sequence[str], exp_rows: Sequence[Sequence],
                  order_matters: bool = False, sig_digits: int = 6,
                  match_columns_by_name: bool = True) -> tuple[bool, str]:
    if len(got_rows) != len(exp_rows):
        return False, f"row count {len(got_rows)} != {len(exp_rows)}"
    if len(got_cols) < len(exp_cols):
        return False, "missing columns"
    if match_columns_by_name:
        lower = [c.lower() for c in got_cols]
        try:
            idx = [lower.index(c.lower()) for c in exp_cols]
        except ValueError as e:
            return False, f"column not found: {e}"
    else:
        idx = list(range(len(exp_cols)))
    g = [tuple(_norm(r[i], sig_digits) for i in idx) for r in got_rows]
    e = [tuple(_norm(v, sig_digits) for v in r) for r in exp_rows]
    if order_matters:
        return (g == e, "ok" if g == e else "row order or values differ")
    ok = Counter(map(repr, g)) == Counter(map(repr, e))
    return ok, "ok" if ok else "values differ"
