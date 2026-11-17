import sys, json, time
sys.path.insert(0, "/tmp/claude-0/qa/harness")
import lib
from lib import *
import scen1, scen2, scen3, scen4, scen5, scen6, scen7
cycle = sys.argv[1]; only = sys.argv[2] if len(sys.argv) > 2 else None
t0 = time.time(); F = scen1.fixtures(); print("fixtures", round(time.time()-t0), "s", flush=True)
res = lib.run_all(cycle, only, workers=4, F=F)
out = f"/tmp/claude-0/qa/results_api_{cycle}.json"
json.dump(res, open(out, "w"), indent=1, ensure_ascii=False)
from collections import Counter
print(Counter(r["status"] for r in res), "total", len(res), round(time.time()-t0), "s")
for r in res:
    if r["status"] != "PASS": print(r["status"], r["id"], "|", r["actual"][:200])
