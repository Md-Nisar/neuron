"""DG-00.04: ask Auto Ontology one question through its gateway with the service token, and
append the record (question, SQL, rows, answer, events, seconds) to a JSONL file.

  AO_LOCAL_ENV=... python ask.py http://127.0.0.1:3000 out.jsonl "question"
"""
import json
import os
import sys
import time
import urllib.request

base, out, question = sys.argv[1:4]
env = dict(line.split("=", 1) for line in open(os.environ["AO_LOCAL_ENV"]).read().split())
req = urllib.request.Request(base + "/api/chat/completions", method="POST",
                             data=json.dumps({"question": question}).encode(),
                             headers={"Content-Type": "application/json", "x-api-key": env["AO_API_TOKEN"]})
rec = {"question": question, "sql_seen": [], "steps": 0, "answer": None, "error": None}
started = time.monotonic()
with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=900) as r:
    for raw in r:
        line = raw.decode().strip()
        if not line.startswith("data:"):
            continue
        payload = line.removeprefix("data:").strip()
        if payload == "[DONE]":
            break
        ev = json.loads(payload)
        if ev["type"] == "step":
            rec["steps"] += 1
        elif ev["type"] == "sql":
            rec["sql_seen"].append(ev.get("sql") or ev.get("content"))
        elif ev["type"] == "result":
            a = ev["answer"]
            rec["answer"] = {k: a.get(k) for k in ("response", "sql_code", "sql_response_from_db")}
        elif ev["type"] == "error":
            rec["error"] = ev.get("message")
rec["seconds"] = round(time.monotonic() - started, 1)
with open(out, "a") as f:
    f.write(json.dumps(rec, default=str) + "\n")
a = rec["answer"] or {}
print(json.dumps({"seconds": rec["seconds"], "error": rec["error"], "sql": a.get("sql_code"),
                  "rows": str(a.get("sql_response_from_db"))[:400], "response": (a.get("response") or "")[:400]}, indent=1))
