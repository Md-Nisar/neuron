import json, os, re, time, uuid, traceback, httpx, threading
API = "http://127.0.0.1:8000"
IDP = "http://localhost:8180"
CORPUS = "/tmp/claude-0/qa/corpus"
RUN = uuid.uuid4().hex[:6]
SCEN = []          # (meta, fn)
_tok = {}
_lock = threading.Lock()
client = httpx.Client(base_url=API, timeout=240, trust_env=False)
idp = httpx.Client(base_url=IDP, timeout=20, trust_env=False)

def mint(sub, **q):
    key = (sub, tuple(sorted(q.items())))
    with _lock:
        if key not in _tok:
            _tok[key] = idp.get("/qa/mint", params={"sub": f"{sub}-{RUN}" if not q.get("raw") else sub, **{k: v for k, v in q.items() if k != "raw"}}).text
        return _tok[key]

def H(sub, **q):
    return {"Authorization": f"Bearer {mint(sub, **q)}"}

def api(method, path, sub=None, token=None, headers=None, **kw):
    h = dict(headers or {})
    if token: h["Authorization"] = f"Bearer {token}"
    elif sub: h.update(H(sub))
    return client.request(method, path, headers=h, **kw)

def make_kb(sub, name="KB", **extra):
    r = api("POST", "/v1/knowledge/bases", sub, json={"name": name, **extra})
    assert r.status_code == 201, (r.status_code, r.text)
    return r.json()["kb_id"]

def upload(sub, kb, filename_or_path, data=None, mime=None, headers=None, title=None, token=None):
    if data is None:
        p = filename_or_path if filename_or_path.startswith("/") else f"{CORPUS}/{filename_or_path}"
        data = open(p, "rb").read(); filename = os.path.basename(p)
    else:
        filename = filename_or_path
    mime = mime or {"md": "text/markdown", "txt": "text/plain", "csv": "text/csv"}.get(filename.rsplit(".", 1)[-1], "application/octet-stream")
    return api("POST", f"/v1/knowledge/bases/{kb}/documents", sub, token=token, headers=headers,
               files={"file": (filename, data, mime)}, data={"title": title} if title else None)

def wait_doc(sub, doc_id, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = api("GET", f"/v1/knowledge/documents/{doc_id}", sub)
        if r.status_code == 200 and r.json()["status"] in ("ready", "failed"):
            return r.json()
        time.sleep(1)
    return {"status": "timeout"}

def up_ready(sub, kb, name, **kw):
    r = upload(sub, kb, name, **kw)
    assert r.status_code == 202, (r.status_code, r.text)
    d = wait_doc(sub, r.json()["doc_id"])
    return r.json()["doc_id"], d

def search(sub, q, kbs=None, limit=5, **kw):
    body = {"query": q, "limit": limit}
    if kbs is not None: body["kb_ids"] = kbs
    return api("POST", "/v1/knowledge/search", sub, json=body, **kw)

def ask(sub, msg, kbs=None, thread=None):
    body = {"message": msg}
    if kbs is not None: body["knowledge_base_ids"] = kbs
    if thread: body["thread_id"] = thread
    return api("POST", "/v1/agent/invoke", sub, json=body)

class Skip(Exception): pass
def check(cond, actual, obs=""):
    return (actual, bool(cond), obs)

def scenario(sid, area, desc, pre, steps, expected, kind="API"):
    def deco(fn):
        SCEN.append((dict(id=sid, area=area, kind=kind, description=desc, preconditions=pre, steps=steps, expected=expected), fn))
        return fn
    return deco

def run_all(cycle, only=None, workers=4, F=None):
    from concurrent.futures import ThreadPoolExecutor
    out = []
    def one(item):
        meta, fn = item
        t0 = time.time()
        try:
            actual, ok, obs = fn(F)
            status = "PASS" if ok else "FAIL"
        except Skip as e:
            actual, status, obs = str(e), "BLOCKED", ""
        except Exception as e:
            actual, status, obs = f"exception: {type(e).__name__}: {e}"[:400], "FAIL", traceback.format_exc()[-600:]
        return {**meta, "actual": str(actual)[:900], "status": status, "observations": str(obs)[:900], "seconds": round(time.time() - t0, 1), "cycle": cycle}
    items = [s for s in SCEN if not only or re.match(only, s[0]["id"])]
    with ThreadPoolExecutor(workers) as ex:
        out = list(ex.map(one, items))
    return out
