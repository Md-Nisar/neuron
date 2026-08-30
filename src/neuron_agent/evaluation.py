"""Deterministic local evaluation runner."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast


def load_eval_cases(path: Path) -> list[dict[str, object]]:
    return cast("list[dict[str, object]]", json.loads(path.read_text(encoding="utf-8")))


def main() -> None:
    path = Path("tests/fixtures/eval_cases.json")
    cases = load_eval_cases(path)
    print(f"Loaded {len(cases)} evaluation cases from {path}")
