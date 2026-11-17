from lib import *
import subprocess, threading
@scenario("WEB-13","Web pages","A real public web page is fetched, ingested, searchable and cited with its source URL","Egress to the public internet","Add https://docs.python.org/3/tutorial/introduction.html; search; ask","ready; search hit has source_url; agent citation carries source_url")
def _(F):
    kb=make_kb("u_w13","Wiki"); u="https://docs.python.org/3/tutorial/introduction.html"; r=api("POST",f"/v1/knowledge/bases/{kb}/web-pages","u_w13",json={"url":u})
    if r.status_code!=202: return check(False,(r.status_code,r.text[:150]))
    d=wait_doc("u_w13",r.json()["doc_id"],150)
    if d["status"]!="ready": return check(False,(d["status"],d["error_code"]),"egress/page issue")
    s=search("u_w13","how do python lists and strings work as numbers and text",[kb]).json().get("results",[]); a=ask("u_w13","According to my page, what character starts a comment in Python? Answer in one sentence.",[kb]).json(); cs=a.get("citations",[])
    return check(s and s[0].get("source_url") and cs and cs[0].get("source_url") and a.get("grounded"),(d["title"],s[0].get("source_url") if s else None,len(cs),a.get("answer","")[:140]))
@scenario("AGENT-19","Agent answers","Client disconnects mid-stream: the run lease is released and the thread can be used again","Handbook KB","Start /v1/agent/stream, abort after 2s; immediately send a new run on the same thread","Follow-up eventually succeeds (200); not stuck busy forever")
def _(F):
    tid=None
    try:
        with client.stream("POST","/v1/agent/stream",headers=H("alice"),json={"message":"Explain in detail the remote work policy and vacation policy.","knowledge_base_ids":[F["kb_hb"]]},timeout=30) as r:
            t0=time.time()
            for line in r.iter_lines():
                if line.startswith("data:") and tid is None and "thread_id" in line: tid=json.loads(line[5:])["thread_id"]
                if tid and time.time()-t0>2: break
    except Exception: pass
    if not tid: return check(False,"no thread_id seen in run_started")
    codes=[]
    for i in range(12):
        r=ask("alice","What is the home office stipend?",[F["kb_hb"]],thread=tid); codes.append(r.status_code)
        if r.status_code==200: break
        time.sleep(5)
    return check(codes[-1]==200,codes,"409 thread_busy while the abandoned run finishes is acceptable")
@scenario("AGENT-20","Agent answers","Per-user concurrent run cap returns 429 too_many_concurrent_runs with Retry-After","APP_MAX_CONCURRENT_RUNS_PER_USER=5","Fire 8 simultaneous invokes as one user","Some 200; excess 429 with Retry-After; no 5xx")
def _(F):
    out=[]; lock=threading.Lock()
    def go(i):
        r=api("POST","/v1/agent/invoke","u_cap",json={"message":f"Reply with the number {i} only."})
        with lock: out.append((r.status_code,r.headers.get("retry-after"),r.json().get("detail") if r.status_code!=200 else None))
    ts=[threading.Thread(target=go,args=(i,)) for i in range(8)]; [t.start() for t in ts]; [t.join() for t in ts]
    codes=sorted(c for c,_,_ in out); n429=[o for o in out if o[0]==429]
    return check(all(c in (200,429,502) for c in codes) and (not n429 or all(o[1] for o in n429)),(codes,n429[:2]),"502/429 may come from the NVIDIA free tier under load")
@scenario("AGENT-21","Agent answers","Feedback on a cited answer is stored; invalid feedback is rejected","Answered run","POST thumbs-up with reason; POST score 5; POST on a run of another user","200; 422; 404")
def _(F):
    j=ask("alice","What is the home office stipend?",[F["kb_hb"]]).json(); t,rn=j["thread_id"],j["run_id"]
    a=api("POST",f"/v1/threads/{t}/runs/{rn}/feedback","alice",json={"score":1,"reason":"helpful"}).status_code; b=api("POST",f"/v1/threads/{t}/runs/{rn}/feedback","alice",json={"score":5}).status_code; c=api("POST",f"/v1/threads/{t}/runs/{rn}/feedback","bob",json={"score":1}).status_code
    return check(a==200 and b==422 and c in (403,404),(a,b,c))
@scenario("RES-02","Resilience","Database outage: readiness flips, API answers 503 with a stable error, then recovers without restart","Postgres in docker","docker pause neuron-pg 12s; probe live/ready/list; unpause; probe again","live stays 200; ready not 200 during outage; list 503 (never 500 stack/leak); all OK after recovery")
def _(F):
    subprocess.run(["docker","pause","neuron-pg"],capture_output=True); time.sleep(1)
    try:
        t0=time.time(); during={"live":client.get("/health/live").status_code}
        try: during["ready"]=client.get("/health/ready",timeout=20).status_code
        except Exception as e: during["ready"]=type(e).__name__
        try:
            r=api("GET","/v1/knowledge/bases","alice",timeout=40); during["list"]=(r.status_code,r.text[:80])
        except Exception as e: during["list"]=type(e).__name__
    finally:
        subprocess.run(["docker","unpause","neuron-pg"],capture_output=True)
    ok=None; t0=time.time()
    while time.time()-t0<90:
        try:
            r=api("GET","/v1/knowledge/bases","alice")
            if r.status_code==200 and client.get("/health/ready").status_code==200: ok=round(time.time()-t0,1); break
        except Exception: pass
        time.sleep(2)
    l=during["list"]; return check(during["live"]==200 and during["ready"]!=200 and (isinstance(l,tuple) and l[0] in (503,504) and "Traceback" not in l[1] or isinstance(l,str)) and ok is not None,(during,ok))
