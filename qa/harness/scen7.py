from lib import *
@scenario("DOC-36","Documents","500-character filename is handled (title capped) without a 5xx","Base","Upload file named 'x'*496+'.txt'","202 with a bounded title, or a clean 4xx")
def _(F):
    kb=make_kb("u_b1"); r=upload("u_b1",kb,"x"*496+".txt",data=b"long name doc",mime="text/plain")
    if r.status_code!=202: return check(r.status_code in (400,413,422),(r.status_code,r.text[:100]))
    d=wait_doc("u_b1",r.json()["doc_id"],60); return check(d["status"]=="ready" and len(d["title"])<=300,(d["status"],len(d["title"])))
@scenario("DOC-37","Documents","Upload title over 300 characters is rejected","Base","Upload with title='t'*301","422")
def _(F):
    kb=make_kb("u_b2"); r=upload("u_b2",kb,"a.txt",data=b"x",mime="text/plain",title="t"*301); return check(r.status_code==422,(r.status_code,r.text[:100]))
@scenario("DOC-38","Documents","Document list offset beyond total returns an empty page, not an error","Base with 1 doc","GET documents?offset=1000","200, documents=[], total=1")
def _(F):
    r=api("GET",f"/v1/knowledge/bases/{F['kb_hb']}/documents?offset=1000","alice"); j=r.json(); return check(r.status_code==200 and j["documents"]==[] and j["total"]>=1,(r.status_code,j["total"],len(j["documents"])))
@scenario("AUTH-13","Auth","CORS: a foreign Origin gets no Access-Control-Allow-Origin; the app origin does","cors_allowed_origins=[http://localhost:5173]","OPTIONS preflight with Origin evil.example and with localhost:5173","evil: no ACAO header; app origin: ACAO echoed")
def _(F):
    h={"Access-Control-Request-Method":"POST","Access-Control-Request-Headers":"authorization,content-type"}
    e=client.options("/v1/knowledge/search",headers={**h,"Origin":"https://evil.example"}); g=client.options("/v1/knowledge/search",headers={**h,"Origin":"http://localhost:5173"}); return check("access-control-allow-origin" not in e.headers and g.headers.get("access-control-allow-origin")=="http://localhost:5173",(e.status_code,dict(e.headers).get("access-control-allow-origin"),g.headers.get("access-control-allow-origin")))
@scenario("KB-22","Knowledge base","Whitespace in names is normalised (outer trimmed, inner collapsed)","Signed in","Create ' Team   Docs '","Stored as 'Team Docs'")
def _(F):
    r=api("POST","/v1/knowledge/bases","u_b3",json={"name":"  Team    Docs  "}); return check(r.status_code==201 and r.json()["name"]=="Team Docs",(r.status_code,r.text[:100]))
@scenario("SHARE-11","Sharing","Role matching is case-sensitive and exact (no accidental widening)","Grant to 'Finance'","Holder of 'finance' and holder of 'FINANCE' list bases","Neither sees it (exact match); holder of 'Finance' does")
def _(F):
    kb=make_kb("u_b4","CaseKB"); api("PUT",f"/v1/knowledge/bases/{kb}/grants","u_b4",json={"grants":[{"role":"Finance","access":"read"}]}); see=lambda role: any(b["kb_id"]==kb for b in api("GET","/v1/knowledge/bases",token=idp.get("/qa/mint",params={"sub":f"m-{role}-{RUN}","roles":role}).text).json()["bases"])
    return check(see("Finance") and not see("finance") and not see("FINANCE"),(see("Finance"),see("finance"),see("FINANCE")))
@scenario("SRCH-22","Search","500-character multi-byte query (limit) is accepted","Handbook KB","Search 500 emoji/CJK characters","200")
def _(F):
    r=search("alice","日"*500,[F["kb_hb"]]); return check(r.status_code==200,r.status_code)
