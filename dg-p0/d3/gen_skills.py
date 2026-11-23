"""Generate sql/04_skills_seed.sql for the D3 skills schema (DG-00.01). Deterministic.

Usage: python3 gen_skills.py > sql/04_skills_seed.sql
Standard library only. Names are synthetic; no real people.
"""

from __future__ import annotations

import datetime as dt
import random

SEED = 20261124
rng = random.Random(SEED)

REGIONS = ["EMEA", "APAC", "AMER"]
DEPARTMENTS = ["Engineering", "Data", "Consulting", "Support"]
TITLES = ["Engineer", "Analyst", "Consultant", "Team Lead", "Manager"]
TITLE_LEVELS = {
    "Engineer": (1, 4),
    "Analyst": (1, 4),
    "Consultant": (2, 5),
    "Team Lead": (3, 5),
    "Manager": (4, 5),
}
SKILLS = {
    "Technical": [
        "Python",
        "SQL",
        "Cloud Architecture",
        "Networking",
        "Security Engineering",
        "Data Modelling",
        "Testing",
        "DevOps",
    ],
    "Leadership": [
        "Coaching",
        "Delegation",
        "Strategic Planning",
        "Decision Making",
        "Hiring",
        "Conflict Resolution",
    ],
    "Communication": [
        "Presenting",
        "Technical Writing",
        "Stakeholder Management",
        "Negotiation",
        "Facilitation",
    ],
    "Domain": [
        "Retail",
        "Finance",
        "Healthcare",
        "Manufacturing",
        "Public Sector",
        "Telecoms",
        "Energy",
        "Logistics",
        "Insurance",
        "Media",
        "Education",
    ],
}
CYCLES = [
    (1, "2024-H1", dt.date(2024, 1, 1), dt.date(2024, 6, 30)),
    (2, "2024-H2", dt.date(2024, 7, 1), dt.date(2024, 12, 31)),
    (3, "2025-H1", dt.date(2025, 1, 1), dt.date(2025, 6, 30)),
    (4, "2025-H2", dt.date(2025, 7, 1), dt.date(2025, 12, 31)),
]
CERTS = [
    "Cloud Practitioner",
    "Solutions Architect",
    "Data Engineer",
    "Security+",
    "Scrum Master",
    "PMP",
    "ITIL Foundation",
    "Kubernetes Administrator",
]
FIRST = [
    "Aria",
    "Ben",
    "Chen",
    "Dana",
    "Eli",
    "Fatima",
    "Gabe",
    "Hana",
    "Ivan",
    "Jade",
    "Karim",
    "Lina",
    "Marco",
    "Nia",
    "Oscar",
    "Priya",
    "Quentin",
    "Rosa",
    "Sven",
    "Tara",
    "Umar",
    "Vera",
    "Wei",
    "Yusuf",
    "Zoe",
]
LAST = [
    "Adler",
    "Bauer",
    "Costa",
    "Dubois",
    "Eze",
    "Fong",
    "Garcia",
    "Hansen",
    "Ibrahim",
    "Jensen",
    "Kato",
    "Lund",
    "Mehta",
    "Nakamura",
    "Oduya",
    "Petrov",
    "Quinn",
    "Reyes",
    "Schmidt",
    "Tanaka",
    "Ueda",
    "Varga",
    "Weber",
    "Yilmaz",
    "Zhou",
]
NOTES = [
    "Strong progress since last cycle.",
    "Needs more hands-on practice.",
    "Ready for a stretch assignment.",
    "Consistently meets expectations.",
    "Recommend formal training next cycle.",
    "Mentors others effectively.",
    "Score held back by limited project exposure.",
    "Clear improvement in client work.",
]
END = dt.date(2025, 12, 31)


def rand_date(lo: dt.date, hi: dt.date) -> dt.date:
    return lo + dt.timedelta(days=rng.randrange((hi - lo).days + 1))


def lit(v: object) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, str):
        return "'" + v.replace("'", "''") + "'"
    if isinstance(v, dt.date):
        return f"'{v.isoformat()}'"
    return str(v)


def insert(table: str, cols: list[str], rows: list[tuple[object, ...]]) -> str:
    body = ",\n".join("  (" + ", ".join(lit(v) for v in r) + ")" for r in rows)
    return f"INSERT INTO skills.{table} ({', '.join(cols)}) VALUES\n{body};"


def main() -> None:
    departments = []
    for i, (region, dept) in enumerate([(r, d) for r in REGIONS for d in DEPARTMENTS], start=1):
        departments.append((i, f"{dept} {region}", region))

    skills, sid = [], 0
    for cat, names in SKILLS.items():
        for n in names:
            sid += 1
            skills.append((sid, n, cat))
    by_cat = {cat: [s[0] for s in skills if s[2] == cat] for cat in SKILLS}

    employees, eid = [], 0
    for d in departments:
        eid += 1
        head = eid  # department head: a Manager with no line manager
        employees.append(
            [
                eid,
                f"{rng.choice(FIRST)} {rng.choice(LAST)}",
                d[0],
                d[2],
                "Manager",
                5,
                None,
                rand_date(dt.date(2015, 1, 1), dt.date(2021, 12, 31)),
                None,
            ]
        )
        for _ in range(rng.randint(17, 22)):
            eid += 1
            title = rng.choices(TITLES, weights=[6, 4, 4, 2, 1])[0]
            lo, hi = TITLE_LEVELS[title]
            hired = rand_date(dt.date(2016, 1, 1), dt.date(2025, 9, 30))
            left = (
                rand_date(hired + dt.timedelta(days=120), END)
                if rng.random() < 0.12 and hired < dt.date(2025, 6, 1)
                else None
            )
            employees.append(
                [
                    eid,
                    f"{rng.choice(FIRST)} {rng.choice(LAST)}",
                    d[0],
                    d[2],
                    title,
                    rng.randint(lo, hi),
                    head,
                    hired,
                    left,
                ]
            )

    targets = []
    for title in TITLES:
        picks = rng.sample(by_cat["Technical"], 4) + rng.sample(by_cat["Communication"], 2)
        if title in ("Team Lead", "Manager"):
            picks += rng.sample(by_cat["Leadership"], 3)
        if title == "Consultant":
            picks += rng.sample(by_cat["Domain"], 2)
        for s in picks:
            targets.append(
                (title, s, rng.randint(3, 5) if title != "Engineer" else rng.randint(2, 4))
            )
    target_skills = {}
    for title, s, _ in targets:
        target_skills.setdefault(title, []).append(s)

    assessments, notes, certs = [], [], []
    aid = 0
    for e in employees:
        emp_id, _, _, region, title, level, mgr, hired, left = e
        assessor = mgr if mgr is not None else emp_id
        ability = {s: rng.gauss(1.5 + level * 0.6, 0.7) for s in range(1, len(skills) + 1)}
        for cid, _, starts, ends in CYCLES:
            if hired > ends or (left is not None and left < starts):
                continue
            if rng.random() < 0.08:  # missed this cycle
                continue
            pool = target_skills[title] + rng.sample(by_cat["Domain"], 1)
            for s in sorted(set(pool)):
                ability[s] += rng.uniform(-0.1, 0.35)
                aid += 1
                score = max(1, min(5, round(ability[s])))
                when = rand_date(ends - dt.timedelta(days=30), ends)
                assessments.append((aid, emp_id, s, cid, assessor, region, score, when))
                if rng.random() < 0.06:
                    notes.append((aid, region, rng.choice(NOTES)))
        for _ in range(rng.choices([0, 1, 2], weights=[5, 4, 1])[0]):
            issued = rand_date(max(hired, dt.date(2020, 1, 1)), END)
            expires = (
                None if rng.random() < 0.3 else issued + dt.timedelta(days=365 * rng.choice([2, 3]))
            )
            certs.append((len(certs) + 1, emp_id, region, rng.choice(CERTS), issued, expires))

    print(f"-- Generated by gen_skills.py (seed {SEED}). Do not edit by hand.")
    print("BEGIN;")
    print(insert("departments", ["department_id", "name", "region_id"], departments))
    print(
        insert(
            "employees",
            [
                "employee_id",
                "name",
                "department_id",
                "region_id",
                "job_title",
                "level",
                "manager_id",
                "hired_on",
                "left_on",
            ],
            [tuple(e) for e in employees],
        )
    )
    print(insert("skills", ["skill_id", "name", "category"], skills))
    print(insert("assessment_cycles", ["cycle_id", "name", "starts_on", "ends_on"], CYCLES))
    print(insert("role_targets", ["job_title", "skill_id", "target_score"], targets))
    print(
        insert(
            "assessments",
            [
                "assessment_id",
                "employee_id",
                "skill_id",
                "cycle_id",
                "assessor_id",
                "region_id",
                "score",
                "assessed_on",
            ],
            assessments,
        )
    )
    print(
        insert(
            "certifications",
            ["certification_id", "employee_id", "region_id", "name", "issued_on", "expires_on"],
            certs,
        )
    )
    print(insert("assessor_notes", ["assessment_id", "region_id", "note"], notes))
    print("COMMIT;")


if __name__ == "__main__":
    main()
