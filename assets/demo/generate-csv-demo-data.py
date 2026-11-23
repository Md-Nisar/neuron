import csv, random, datetime as dt, sys
out = sys.argv[1]
r = random.Random(2026)
regions = {"North America": ["Priya Raman", "Tom Becker", "Dana Whitfield"],
           "EMEA": ["Lukas Meyer", "Amara Okafor", "Sofia Rossi"],
           "APAC": ["Kenji Watanabe", "Mei Lin Tan", "Arjun Mehta"],
           "LATAM": ["Camila Duarte", "Mateo Silva"]}
weight = {"North America": 4, "EMEA": 3, "APAC": 3, "LATAM": 1}
catalog = {"Electronics": [("Trailhead GPS Watch", 249.0), ("Summit Headlamp Pro", 59.0), ("Basecamp Solar Charger", 89.0)],
           "Apparel": [("Alpine Shell Jacket", 189.0), ("Merino Base Layer", 79.0), ("Ridge Hiking Pants", 95.0)],
           "Camping": [("Cascade 2P Tent", 329.0), ("Nomad Sleeping Bag", 149.0), ("Ember Camp Stove", 69.0)],
           "Footwear": [("Granite Trail Boots", 179.0), ("Vapor Trail Runners", 129.0)]}
cats = list(catalog)
status = ["Delivered"]*86 + ["Shipped"]*5 + ["Returned"]*5 + ["Cancelled"]*4
rows = []
d0 = dt.date(2026, 1, 1)
for i in range(1, 641):
    day = d0 + dt.timedelta(days=int(r.random()**0.9 * 330))
    reg = r.choices(list(regions), [weight[k] for k in regions])[0]
    rep = r.choice(regions[reg])
    cat = r.choices(cats, [3, 3, 2, 2])[0]
    prod, price = r.choice(catalog[cat])
    # seasonality: camping peaks in summer, apparel in autumn
    units = max(1, int(r.gauss(6, 3)))
    if cat == "Camping" and day.month in (6, 7, 8): units += 4
    if cat == "Apparel" and day.month in (10, 11): units += 3
    disc = r.choice([0, 0, 0, 5, 10, 10, 15, 20]) if cat != "Electronics" else r.choice([0, 0, 5, 5, 10])
    rev = round(units * price * (1 - disc / 100), 2)
    rows.append([f"ORD-{20260000+i}", day.isoformat(), f"Q{(day.month-1)//3+1}", reg, rep, cat, prod, units, price, disc, rev, r.choice(status)])
rows.sort(key=lambda x: (x[1], x[0]))
with open(f"{out}/meridian-sales-orders-2026.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["order_id","order_date","quarter","region","sales_rep","category","product","units","unit_price_usd","discount_pct","revenue_usd","status"])
    w.writerows(rows)

teams = {"Billing": 1.0, "Technical": 2.2, "Shipping": 1.4, "Returns": 0.9}
rows = []
for i in range(1, 421):
    day = dt.date(2026, 7, 1) + dt.timedelta(days=r.randrange(92))
    team = r.choices(list(teams), [2, 4, 3, 2])[0]
    pri = r.choices(["Low", "Medium", "High", "Urgent"], [30, 40, 22, 8])[0]
    base = {"Low": 30, "Medium": 18, "High": 12, "Urgent": 6}[pri] * teams[team]
    hrs = round(max(0.5, r.gauss(base, base * 0.45)), 1)
    csat = max(1, min(5, round(r.gauss(4.5 - hrs / 40 - (0.4 if team == "Shipping" else 0), 0.7))))
    rows.append([f"TKT-{70000+i}", day.isoformat(), team, pri, hrs, csat, r.choice(["Email","Chat","Phone"])])
rows.sort(key=lambda x: (x[1], x[0]))
with open(f"{out}/meridian-support-tickets-q3-2026.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["ticket_id","opened_date","team","priority","hours_to_resolve","csat_score","channel"])
    w.writerows(rows)
