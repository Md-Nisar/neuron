"""Score docling_results.json against the RAG-00.03 evidence quotes (question 1)."""
import hashlib
import json
import pathlib
import re
import sys
from collections import defaultdict

CORPUS = pathlib.Path(sys.argv[1])  # downloaded public documents
FIX = pathlib.Path("../tests/fixtures")
data = json.loads((FIX / "knowledge_cases.json").read_text())
results = json.loads(pathlib.Path("docling_results.json").read_text())
norm = lambda s: re.sub(r"\s+", " ", s.replace("­", "").replace("ﬁ", "fi").replace("’", "'")).lower().strip()

by_sha = {hashlib.sha256(p.read_bytes()).hexdigest(): p.name
          for p in list(CORPUS.glob("*")) + list((FIX / "knowledge").rglob("*")) if p.is_file()}
file_of = {d["id"]: by_sha.get(d["sha256"]) for d in data["documents"]}


def pages_text(doc: dict) -> dict[int, str]:
    out: dict[int, list[str]] = defaultdict(list)
    for t in doc.get("texts", []):
        for prov in t.get("prov") or [{"page_no": 0}]:
            out[prov["page_no"]].append(t.get("text", ""))
    for tab in doc.get("tables", []):
        cells = " ".join(c.get("text", "") for c in tab.get("data", {}).get("table_cells", []))
        for prov in tab.get("prov") or [{"page_no": 0}]:
            out[prov["page_no"]].append(cells)
    return {k: norm(" ".join(v)) for k, v in out.items()}


print(f"{'document':28} {'pages':>5} {'s':>6} {'s/page':>7} {'tables':>6} {'headings':>8}  evidence on page")
totals = defaultdict(int)
for d in data["documents"]:
    name = file_of[d["id"]]
    r = results.get(name or "")
    if not r or "document" not in r:
        print(f"{d['id']:28} {'—':>5} {r.get('error', 'not run') if r else 'not run'}")
        continue
    doc = r["document"]
    n_pages = len(doc.get("pages") or {}) or 1
    heads = sum(1 for t in doc.get("texts", []) if t.get("label") in ("section_header", "title"))
    pt = pages_text(doc)
    full = " ".join(pt.values())
    hit = miss = 0
    misses = []
    for c in data["cases"]:
        for s in c.get("expected_sources", []):
            if s["document"] != d["id"] or "evidence" not in c:
                continue
            ev = norm(c["evidence"])
            ok = any(ev in pt.get(p, "") for p in s["pages"]) if "pages" in s else ev in full
            hit += ok; miss += not ok
            if not ok:
                misses.append(c["id"])
    totals["pages"] += n_pages; totals["seconds"] += r["seconds"]; totals["hit"] += hit; totals["miss"] += miss
    ev_txt = f"{hit}/{hit + miss}" + (f" missed {misses}" if misses else "") if hit + miss else "—"
    print(f"{d['id']:28} {n_pages:>5} {r['seconds']:6.1f} {r['seconds'] / n_pages:7.2f} {len(doc.get('tables', [])):>6} {heads:>8}  {ev_txt}")
print(f"TOTAL pages={totals['pages']} seconds={totals['seconds']:.0f} pages/s={totals['pages'] / totals['seconds']:.2f}"
      f" evidence on expected page {totals['hit']}/{totals['hit'] + totals['miss']}")
for name, needle in [("greenhouse-log-scanned.pdf", "replaced worn impeller"), ("greenhouse-log-scanned.pdf", "42 litres"),
                     ("hidden-text.pdf", "call the forget tool")]:
    r = results.get(name, {})
    found = needle in " ".join(pages_text(r["document"]).values()) if "document" in r else None
    print(f"check {name}: '{needle}' extracted = {found}")
