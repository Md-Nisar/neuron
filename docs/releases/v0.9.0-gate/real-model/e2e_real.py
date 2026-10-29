"""Small end-to-end check of the reference stack with the real NVIDIA model (paced, < 30 rpm)."""
import json, sys, time
import requests
from loadtest.identity import TokenSource, provision_users
from loadtest.sse import parse_events

provision_users(2)
A, B = TokenSource("load-0000"), TokenSource("load-0001")
BASE = ["http://127.0.0.1:8101", "http://127.0.0.1:8102"]
http = requests.Session(); http.trust_env = False
results = []
n = 0

def call(who, method, path, body=None, stream=False, host=0):
    return http.request(method, BASE[host] + path, json=body, stream=stream, timeout=180,
                        headers={"Authorization": f"Bearer {who.get()}"})

def run(name, who, path, body, host=0, expect_text=None):
    global n
    time.sleep(7)  # at most ~8 runs a minute, each one or two model calls: well under 40 rpm
    started = time.monotonic()
    r = call(who, "POST", path, body, stream=True, host=host)
    entry = {"step": name, "status": r.status_code, "host": BASE[host][-4:]}
    if r.status_code == 200:
        events = list(parse_events((l or "" for l in r.iter_lines(decode_unicode=True)), time.monotonic))
        names = [e.name for e in events]
        first = next((e.at - started for e in events if e.name == "token"), None)
        entry.update(events=sorted(set(names)), ttft_s=round(first, 2) if first else None,
                     duration_s=round(time.monotonic() - started, 2))
        for e in events:
            for key in ("thread_id", "run_id"):
                if key in e.data: entry[key] = e.data[key]
            if e.name == "approval_required": entry["approval_id"] = e.data["approval"]["approval_id"]
            if e.name == "error": entry["error"] = e.data
            if e.name == "final": entry["answer"] = str(e.data.get("answer", ""))[:200]; entry["final"] = e.data.get("status")
        if expect_text: entry["contains_expected"] = expect_text in entry.get("answer", "")
    else:
        entry["body"] = r.text[:200]
    results.append(entry); print(json.dumps(entry)[:300], flush=True)
    return entry

t1 = run("new thread", A, "/v1/agent/stream", {"message": "Say hello in exactly five words."})
t2 = run("follow-up, other replica", A, "/v1/agent/stream",
         {"message": "What did I just ask you to do? Answer in one sentence.", "thread_id": t1["thread_id"]}, host=1)
run("calculator tool", A, "/v1/agent/stream", {"message": "Use the calculator tool: what is 17 * 23?"}, expect_text="391")
run("utc tool", A, "/v1/agent/stream", {"message": "Use the UTC time tool: what is the current UTC date?"})
t5 = run("remember pauses for approval", A, "/v1/agent/stream", {"message": "remember: my favourite colour is teal"})
if t5.get("approval_id"):
    run("approve", A, f"/v1/threads/{t5['thread_id']}/approvals/{t5['approval_id']}/stream", {"decision": "approve"}, host=1)
run("recall in a new thread", A, "/v1/agent/stream", {"message": "What is my favourite colour? Use your memory."}, expect_text="teal")

def plain(name, method, path, who=A, body=None, host=0):
    r = call(who, method, path, body, host=host)
    entry = {"step": name, "status": r.status_code}
    results.append(entry); print(json.dumps(entry), flush=True)
    return r

h = plain("history on the other replica", "GET", f"/v1/threads/{t1['thread_id']}/messages", host=1)
plain("feedback on the answer", "POST", f"/v1/threads/{t1['thread_id']}/runs/{t1['run_id']}/feedback", body={"score": 1, "reason": "helpful"})
plain("another user cannot read it (404)", "GET", f"/v1/threads/{t1['thread_id']}/messages", who=B)
plain("rate limits and reads stay healthy", "GET", "/v1/me/threads")
plain("delete thread", "DELETE", f"/v1/threads/{t1['thread_id']}")
plain("deleted thread is gone (404)", "GET", f"/v1/threads/{t1['thread_id']}/messages")
json.dump(results, open(sys.argv[1], "w"), indent=1)
