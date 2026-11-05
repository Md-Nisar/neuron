# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Tool results that carry user or retrieved text, framed as one block of data."""

from __future__ import annotations

import json
from typing import Any


def frame(preamble: str, tag: str, payload: Any) -> str:
    """`payload` as JSON inside `<tag>`, after `preamble`. `<` is escaped, so text in the
    payload cannot close the block or pose as text outside it."""
    body = json.dumps(payload, ensure_ascii=True).replace("<", chr(92) + "u003c")
    return f"{preamble}\n<{tag}>\n{body}\n</{tag}>"
