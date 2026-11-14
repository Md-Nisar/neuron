# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""The table eval fixture (RAG-11.01): a synthetic orders table and questions about it.

Most questions need every row (a total, a count, an average, the largest group), more rows than
search returns; two are lookups of one row, which search alone should answer. The rows come
from a fixed seed and each answer is computed here. Only the questions are committed; tests
build the table with `build()`:

    python3 scripts/build_table_eval.py          # rewrite the questions
    python3 scripts/build_table_eval.py --check  # exit 1 if they differ from what is committed
"""

from __future__ import annotations

import csv
import io
import json
import random
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "tests/fixtures/knowledge/table_cases.json"

ROWS = 1500
REGIONS = ("North", "South", "East", "West")
PRODUCTS = {  # name -> unit price
    "Desk lamp": 24.5,
    "Office chair": 189.0,
    "Monitor arm": 79.25,
    "Keyboard": 49.99,
    "Notebook pack": 6.75,
    "Webcam": 64.0,
}
HEADER = ("order_id", "order_date", "region", "product", "units", "unit_price")


def rows() -> list[tuple[str, str, str, str, int, float]]:
    rng = random.Random(1101)  # noqa: S311 - a fixed seed for a reproducible fixture
    start, days = date(2026, 1, 1), 181  # 1 January to 30 June 2026
    out = []
    for n in range(1, ROWS + 1):
        product = rng.choice(list(PRODUCTS))
        out.append(
            (
                f"O-{n:05d}",
                (start + timedelta(days=rng.randrange(days))).isoformat(),
                rng.choices(REGIONS, weights=(4, 3, 3, 2))[0],
                product,
                rng.randint(1, 20),
                PRODUCTS[product],
            )
        )
    return out


def _only(counts: dict[str, float], pick: str) -> str:
    """The single key with the largest (or smallest) value; a tie would make the case ambiguous."""
    best = (max if pick == "max" else min)(counts.values())
    winners = [k for k, v in counts.items() if v == best]
    assert len(winners) == 1, f"tie: {winners}"
    return winners[0]


def _number(n: int) -> list[str]:
    return [str(n), f"{n:,}"] if n >= 1000 else [str(n)]


def cases(data: list[tuple[str, str, str, str, int, float]]) -> list[dict[str, object]]:
    units_sold: dict[str, float] = defaultdict(float)
    for _, _, _, product, units, _ in data:
        units_sold[product] += units
    lamp = [units for _, _, _, product, units, _ in data if product == "Desk lamp"]
    west_q2 = sum(
        units * price
        for _, day, region, _, units, price in data
        if region == "West" and day >= "2026-04-01"
    )
    order = data[41]
    late = data[1336]

    def case(i: int, kind: str, question: str, answers: list[str]) -> dict[str, object]:
        return {"id": f"table-{i:03d}", "kind": kind, "question": question, "answers": answers}

    return [
        case(1, "aggregate", "In my orders spreadsheet, how many units were sold in the North"
             " region in total?", _number(sum(r[4] for r in data if r[2] == "North"))),
        case(2, "aggregate", "In my orders spreadsheet, how many orders were placed in March"
             " 2026?", [str(sum(1 for r in data if r[1].startswith("2026-03")))]),
        case(3, "aggregate", "In my orders spreadsheet, which product sold the most units in"
             " total?", [_only(units_sold, "max")]),
        case(4, "aggregate", "In my orders spreadsheet, what is the average number of units per"
             " order for the Desk lamp, to one decimal place?",
             [f"{sum(lamp) / len(lamp):.1f}"]),
        case(5, "aggregate", "In my orders spreadsheet, what was the total revenue (units times"
             " unit price) in the West region from April to June 2026, to the cent?",
             [f"{west_q2:.2f}", f"{west_q2:,.2f}"]),
        case(6, "aggregate", "In my orders spreadsheet, which region had the fewest orders?",
             [_only(dict(Counter(r[2] for r in data)), "min")]),
        case(7, "lookup", f"In my orders spreadsheet, how many units did order {order[0]} have?",
             [str(order[4])]),
        case(8, "lookup", f"In my orders spreadsheet, on what date was order {late[0]} placed?",
             [late[1]]),
    ]  # fmt: skip


def build() -> tuple[str, str]:
    data = rows()
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(HEADER)
    writer.writerows(data)
    fixture = {
        "version": "table-eval-1",
        "table": "orders.csv",
        "title": "Orders, January to June 2026",
        "rows": ROWS,
        "cases": cases(data),
    }
    return out.getvalue(), json.dumps(fixture, indent=2) + "\n"


def main(argv: list[str]) -> int:
    _, fixture = build()
    if "--check" in argv:
        same = CASES.read_text(encoding="utf-8") == fixture
        print("table eval fixture is up to date" if same else "table eval fixture is stale")
        return 0 if same else 1
    CASES.write_text(fixture, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
