"""Generate sql/03_seed.sql for the D3 sales mart (DG-00.01). Deterministic: same seed, same file.

Usage: python3 gen_seed.py > sql/03_seed.sql
Standard library only. Names are synthetic; no real people or companies.
"""

from __future__ import annotations

import datetime as dt
import random
from decimal import ROUND_HALF_UP, Decimal

SEED = 20261123
rng = random.Random(SEED)

REGIONS = [
    ("EMEA", "Europe, Middle East and Africa"),
    ("APAC", "Asia Pacific"),
    ("AMER", "Americas"),
]
COUNTRIES = [
    ("DE", "Germany", "EMEA"),
    ("FR", "France", "EMEA"),
    ("GB", "United Kingdom", "EMEA"),
    ("AE", "United Arab Emirates", "EMEA"),
    ("JP", "Japan", "APAC"),
    ("AU", "Australia", "APAC"),
    ("IN", "India", "APAC"),
    ("SG", "Singapore", "APAC"),
    ("US", "United States", "AMER"),
    ("CA", "Canada", "AMER"),
    ("BR", "Brazil", "AMER"),
]
COUNTRY_REGION = {c: r for c, _, r in COUNTRIES}
START, END = dt.date(2024, 1, 1), dt.date(2025, 12, 31)

NAME_A = [
    "North",
    "Blue",
    "Silver",
    "Bright",
    "Iron",
    "Green",
    "Swift",
    "Prime",
    "Clear",
    "Summit",
    "Harbor",
    "Cedar",
    "Atlas",
    "Nova",
    "Orbit",
    "Delta",
    "Maple",
    "Coral",
    "Granite",
    "Echo",
]
NAME_B = [
    "Logistics",
    "Systems",
    "Retail",
    "Foods",
    "Labs",
    "Energy",
    "Health",
    "Media",
    "Works",
    "Partners",
    "Motors",
    "Textiles",
    "Analytics",
    "Pharma",
    "Studios",
]
SUFFIX = ["Ltd", "GmbH", "Inc", "Pty", "SA", "Co", "LLC"]
FIRST = [
    "Alex",
    "Sam",
    "Jordan",
    "Taylor",
    "Morgan",
    "Casey",
    "Riley",
    "Jamie",
    "Avery",
    "Quinn",
    "Rowan",
    "Drew",
    "Kai",
    "Noor",
    "Ravi",
    "Mei",
    "Lena",
    "Omar",
    "Ines",
    "Tomas",
]
LAST = [
    "Becker",
    "Martin",
    "Clarke",
    "Haddad",
    "Sato",
    "Nguyen",
    "Iyer",
    "Tan",
    "Silva",
    "Novak",
    "Okafor",
    "Larsen",
    "Moreau",
    "Kowalski",
    "Rossi",
    "Kim",
    "Lopez",
    "Fischer",
    "Ahmed",
    "Ito",
]
PRODUCTS = {
    "Hardware": [
        "Edge Server",
        "Storage Array",
        "Network Switch",
        "Rack Unit",
        "Workstation",
        "Thin Client",
        "Router",
        "Firewall Appliance",
        "GPU Node",
        "Backup Appliance",
    ],
    "Software": [
        "Analytics Suite",
        "Security Suite",
        "Backup Manager",
        "Monitoring Pro",
        "Database License",
        "Office Bundle",
        "CRM Seats",
        "Design Studio",
        "Compliance Kit",
        "Dev Toolkit",
    ],
    "Services": [
        "Installation",
        "Training Day",
        "Support Plan Basic",
        "Support Plan Premium",
        "Migration Service",
        "Health Check",
        "Consulting Day",
        "Managed Backup",
        "Security Audit",
        "Onboarding",
    ],
    "Accessories": [
        "Cable Kit",
        "Power Supply",
        "Mounting Rail",
        "Keyboard",
        "Docking Station",
        "Monitor 27in",
        "Headset",
        "Spare Drive",
        "Cooling Fan",
        "Adapter Pack",
    ],
}
PRICE_RANGE = {
    "Hardware": (800, 12000),
    "Software": (200, 5000),
    "Services": (300, 4000),
    "Accessories": (15, 400),
}
CENT = Decimal("0.01")


def money(x: float) -> Decimal:
    return Decimal(str(x)).quantize(CENT, rounding=ROUND_HALF_UP)


def rand_date(lo: dt.date, hi: dt.date) -> dt.date:
    return lo + dt.timedelta(days=rng.randrange((hi - lo).days + 1))


def lit(v: object) -> str:
    if isinstance(v, str):
        return "'" + v.replace("'", "''") + "'"
    if isinstance(v, dt.date):
        return f"'{v.isoformat()}'"
    return str(v)


def insert(table: str, cols: list[str], rows: list[tuple[object, ...]]) -> str:
    out = [f"INSERT INTO sales.{table} ({', '.join(cols)}) VALUES"]
    out.append(",\n".join("  (" + ", ".join(lit(v) for v in r) + ")" for r in rows) + ";")
    return "\n".join(out)


def main() -> None:
    regions = REGIONS
    countries = COUNTRIES

    products = []
    pid = 0
    for cat, names in PRODUCTS.items():
        lo, hi = PRICE_RANGE[cat]
        for n in names:
            pid += 1
            products.append((pid, n, cat, money(rng.uniform(lo, hi))))
    price = {p[0]: p[3] for p in products}

    reps = []
    for rid in range(1, 25):
        region = REGIONS[(rid - 1) // 8][0]
        hired = rand_date(dt.date(2019, 1, 1), dt.date(2025, 6, 30))
        reps.append((rid, f"{rng.choice(FIRST)} {rng.choice(LAST)}", region, hired))
    reps_by_region: dict[str, list[tuple]] = {}
    for r in reps:
        reps_by_region.setdefault(r[2], []).append(r)

    customers = []
    seen = set()
    for cid in range(1, 301):
        while True:
            name = f"{rng.choice(NAME_A)} {rng.choice(NAME_B)} {rng.choice(SUFFIX)}"
            if name not in seen:
                seen.add(name)
                break
        cc = rng.choice(countries)[0]
        seg = rng.choices(["Enterprise", "SMB", "Consumer"], weights=[2, 5, 3])[0]
        customers.append(
            (cid, name, seg, cc, COUNTRY_REGION[cc], rand_date(dt.date(2022, 1, 1), END))
        )

    orders, lines, returns = [], [], []
    rid_ret = 0
    for oid in range(1, 3001):
        c = rng.choice(customers)
        region = c[4]
        ordered = rand_date(max(c[5], START), END)
        eligible = [r for r in reps_by_region[region] if r[3] <= ordered] or reps_by_region[region][
            :1
        ]
        rep = rng.choice(eligible)
        if ordered >= dt.date(2025, 12, 1) and rng.random() < 0.5:
            status = "pending"
        else:
            status = "cancelled" if rng.random() < 0.08 else "completed"
        orders.append((oid, c[0], rep[0], region, ordered, status))
        for ln in range(1, rng.randint(1, 4) + 1):
            p = rng.choice(products)[0]
            qty = rng.randint(1, 20)
            unit = (price[p] * Decimal(str(rng.uniform(0.85, 1.0)))).quantize(CENT, ROUND_HALF_UP)
            disc = Decimal(rng.choice([0, 0, 0, 5, 10, 15]))
            lines.append((oid, ln, p, region, qty, unit, disc))
            if status == "completed" and rng.random() < 0.05:
                rid_ret += 1
                when = min(ordered + dt.timedelta(days=rng.randint(5, 60)), END)
                reason = rng.choice(["damaged", "wrong_item", "not_needed", "late_delivery"])
                returns.append((rid_ret, oid, ln, region, when, rng.randint(1, qty), reason))

    comp = []
    for r in reps:
        for year in (2024, 2025):
            if r[3].year <= year:
                base = money(rng.uniform(55000, 120000))
                comp.append((r[0], year, r[2], base, money(float(base) * rng.uniform(0.05, 0.35))))

    print(f"-- Generated by gen_seed.py (seed {SEED}). Do not edit by hand.")
    print("BEGIN;")
    print(insert("regions", ["region_id", "name"], regions))
    print(insert("countries", ["country_code", "name", "region_id"], countries))
    print(insert("products", ["product_id", "name", "category", "list_price"], products))
    print(insert("sales_reps", ["rep_id", "name", "region_id", "hired_on"], reps))
    print(
        insert(
            "customers",
            ["customer_id", "name", "segment", "country_code", "region_id", "created_on"],
            customers,
        )
    )
    print(
        insert(
            "orders",
            ["order_id", "customer_id", "rep_id", "region_id", "ordered_on", "status"],
            orders,
        )
    )
    print(
        insert(
            "order_lines",
            [
                "order_id",
                "line_no",
                "product_id",
                "region_id",
                "quantity",
                "unit_price",
                "discount_pct",
            ],
            lines,
        )
    )
    print(
        insert(
            "returns",
            ["return_id", "order_id", "line_no", "region_id", "returned_on", "quantity", "reason"],
            returns,
        )
    )
    print(
        insert(
            "rep_compensation", ["rep_id", "year", "region_id", "base_salary", "commission"], comp
        )
    )
    print("COMMIT;")


if __name__ == "__main__":
    main()
