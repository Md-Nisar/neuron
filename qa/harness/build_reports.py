"""Merge every run into qa/manual_test_scenarios.{json,csv}: one row per scenario, three cycles."""
import json, csv, glob, os
from collections import Counter
Q="/tmp/claude-0/qa"; OUT="/home/user/neuron/qa"
def load(p): return json.load(open(p)) if os.path.exists(p) else []
by_mtime=lambda fs: sorted(fs,key=os.path.getmtime)
C1=[f"{Q}/results_api_c1_raw.json",f"{Q}/results_api_c1extra.json",f"{Q}/results_api_c1extra2.json",f"{Q}/results_ui_c1_part1.json",f"{Q}/results_ui_c1b.json"]
C2=[f"{Q}/results_api_c2_main.json",f"{Q}/results_ui_c2.json"]+by_mtime([f for f in glob.glob(f"{Q}/results_api_c2[a-z]*.json")+glob.glob(f"{Q}/results_ui_c2[a-z]*.json") if "partial" not in f and "_main" not in f])
C3=[f"{Q}/results_api_c3.json",f"{Q}/results_api_c3b.json",f"{Q}/results_ui_c3.json",f"{Q}/results_ui_c3c.json",f"{Q}/results_kc_c3.json"]
TRIAGE=json.load(open(f"{Q}/harness/triage.json"))
def cycle(files):
    runs={}
    for f in files:
        for r in load(f): runs.setdefault(r["id"],[]).append(r)
    out={}
    for i,rs in runs.items():
        first,last=rs[0],rs[-1]; o=last["observations"]
        if len(rs)>1 and first["status"]!="PASS":
            o=(f"First attempt {first['status']}: {first['actual'][:160]}. Re-run {last['status']}. "+o).strip()
        out[i]=dict(first=first["status"],status=last["status"],actual=last["actual"],observations=o,attempts=len(rs),seconds=last.get("seconds"))
    return out
c=[cycle(C1),cycle(C2),cycle(C3)]
meta={}
for f in C1+C2+C3:
    for r in load(f): meta[r["id"]]=r
def key(x):
    p,n=x.split("-",1); d="".join(ch for ch in n if ch.isdigit()) or "0"; return (p,int(d),n)
rows=[]
for i in sorted(meta,key=key):
    m=meta[i]; row=dict(id=i,area=m["area"],kind=m["kind"],description=m["description"],preconditions=m["preconditions"],steps=m["steps"],expected=m["expected"])
    for n in (1,2,3):
        r=c[n-1].get(i)
        row[f"cycle{n}_first_attempt"]=r["first"] if r else "NOT RUN"; row[f"cycle{n}_status"]=r["status"] if r else "NOT RUN"; row[f"cycle{n}_actual"]=r["actual"] if r else ""
        row[f"cycle{n}_observations"]=r["observations"] if r else "scenario did not exist yet in this cycle (added later)"
    row["final_status"]=row["cycle3_status"]; row["cycle1_triage"]=TRIAGE.get(i,""); rows.append(row)
json.dump(rows,open(f"{OUT}/manual_test_scenarios.json","w"),indent=1,ensure_ascii=False)
with open(f"{OUT}/manual_test_scenarios.csv","w",newline="") as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
for n in (1,2,3): print("cycle",n,"first-attempt",dict(Counter(r[f"cycle{n}_first_attempt"] for r in rows)),"final",dict(Counter(r[f"cycle{n}_status"] for r in rows)))
print("total",len(rows),"| by kind",dict(Counter(r["kind"] for r in rows)),"| final non-pass:",[(r["id"],r["final_status"]) for r in rows if r["final_status"]!="PASS"])
print("areas",dict(Counter(r["area"] for r in rows)))
