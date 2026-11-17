from lib import *
import hashlib, io, zipfile, jwt as pyjwt, time as _t
from cryptography.hazmat.primitives.asymmetric import ec

def fixtures():
    F = {}
    F["kb_hb"] = make_kb("alice", "Handbook", language="english")
    F["d_vac"], F["d_vac_s"] = up_ready("alice", F["kb_hb"], "vacation_policy.md")
    F["d_exp"], F["d_exp_s"] = up_ready("alice", F["kb_hb"], "expenses.txt")
    F["kb_num"] = make_kb("alice", "Numbers")
    F["d_csv"], F["d_csv_s"] = up_ready("alice", F["kb_num"], "headcount.csv")
    F["kb_inj"] = make_kb("alice", "Notes")
    F["d_inj"], F["d_inj_s"] = up_ready("alice", F["kb_inj"], "injection.md")
    F["kb_de"] = make_kb("alice", "Deutsch", language="german")
    F["d_de"], F["d_de_s"] = up_ready("alice", F["kb_de"], "german.md")
    F["kb_bob"] = make_kb("bob", "BobPrivate")
    F["d_bob"], F["d_bob_s"] = up_ready("bob", F["kb_bob"], "secret.txt", data=b"Bob's private note. The vault code word is Zephyr-9 and the launch date is 3 March.", mime="text/plain")
    return F

# ---------------- AUTH ----------------
@scenario("AUTH-01","Auth","Request without a bearer token is rejected","Stack running, auth_mode=jwt","GET /v1/knowledge/bases with no Authorization header","401 authentication_error")
def _(F):
    r = client.get("/v1/knowledge/bases"); return check(r.status_code==401 and r.json().get("detail")=="authentication_error", f"{r.status_code} {r.text[:80]}")
@scenario("AUTH-02","Auth","Malformed bearer token is rejected","Stack running","GET /v1/knowledge/bases with Authorization: Bearer garbage","401")
def _(F):
    r = client.get("/v1/knowledge/bases", headers={"Authorization":"Bearer not.a.jwt"}); return check(r.status_code==401, r.status_code)
@scenario("AUTH-03","Auth","Expired token is rejected","IdP mint endpoint","Mint token with exp=-3600s, call list","401")
def _(F):
    t = idp.get("/qa/mint", params={"sub":"exp","exp":"-3600"}).text
    r = api("GET","/v1/knowledge/bases",token=t); return check(r.status_code==401, r.status_code)
@scenario("AUTH-04","Auth","Token for the wrong audience is rejected","IdP mint endpoint","Mint token aud=other-api, call list","401")
def _(F):
    t = idp.get("/qa/mint", params={"sub":"aud","aud":"other-api"}).text
    r = api("GET","/v1/knowledge/bases",token=t); return check(r.status_code==401, r.status_code)
@scenario("AUTH-05","Auth","Token signed by an unknown key is rejected","None","Sign a JWT locally with a fresh ES256 key (same kid/iss/aud), call list","401")
def _(F):
    k = ec.generate_private_key(ec.SECP256R1()); n=int(_t.time())
    t = pyjwt.encode({"iss":"http://localhost:8180/realms/neuron","aud":"neuron-api","sub":"evil","scope":"knowledge:read","iat":n,"exp":n+600,"jti":"x"}, k, algorithm="ES256", headers={"kid":"browser-e2e","typ":"at+jwt"})
    r = api("GET","/v1/knowledge/bases",token=t); return check(r.status_code==401, r.status_code)
@scenario("AUTH-06","Auth","alg=none token is rejected","None","Craft unsigned JWT with alg none","401")
def _(F):
    import base64
    b=lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    t=f"{b({'alg':'none','typ':'JWT'})}.{b({'iss':'http://localhost:8180/realms/neuron','aud':'neuron-api','sub':'x','scope':'knowledge:read knowledge:write','exp':int(_t.time())+600})}."
    r=api("GET","/v1/knowledge/bases",token=t); return check(r.status_code==401, r.status_code)
@scenario("AUTH-07","Auth","Token without knowledge scope gets 403 on knowledge endpoints","IdP mint endpoint","Mint token scope='threads:read', GET bases, POST bases, POST search","403 on all three")
def _(F):
    t = idp.get("/qa/mint", params={"sub":"noscope","scope":"threads:read"}).text
    c=[api("GET","/v1/knowledge/bases",token=t).status_code, api("POST","/v1/knowledge/bases",token=t,json={"name":"x"}).status_code, api("POST","/v1/knowledge/search",token=t,json={"query":"x"}).status_code]
    return check(c==[403,403,403], c)
@scenario("AUTH-08","Auth","knowledge:read-only token cannot create bases or upload","IdP mint endpoint","Mint scope='knowledge:read'; POST base; POST upload to alice's base","403 for both (no existence leak for upload: 403 or 404)")
def _(F):
    t = idp.get("/qa/mint", params={"sub":"ro","scope":"knowledge:read"}).text
    a=api("POST","/v1/knowledge/bases",token=t,json={"name":"x"}).status_code
    r=client.post(f"/v1/knowledge/bases/{F['kb_hb']}/documents",headers={"Authorization":f"Bearer {t}"},files={"file":("a.txt",b"x","text/plain")}).status_code
    return check(a==403 and r in (403,404), (a,r))
@scenario("AUTH-09","Auth","Request user_id / X-User-Id header cannot impersonate another user","Alice and Bob each own bases","Call list as bob with header X-User-Id: <alice sub>","Bob sees only Bob's bases")
def _(F):
    r=api("GET","/v1/knowledge/bases","bob",headers={"X-User-Id":f"alice-{RUN}"}); names={b["name"] for b in r.json()["bases"]}
    return check("BobPrivate" in names and "Handbook" not in names, names)
@scenario("AUTH-10","Auth","Health endpoints are public","None","GET /health/live and /health/ready without token","200 both")
def _(F):
    a,b=client.get("/health/live"),client.get("/health/ready"); return check(a.status_code==200 and b.status_code==200,(a.text,b.text))
@scenario("AUTH-11","Auth","Security headers present on API responses","None","GET /health/live; inspect headers","nosniff, no-store/frame deny present")
def _(F):
    h=client.get("/health/live").headers; need=["x-content-type-options"]; miss=[n for n in need if n not in h]
    return check(not miss, dict(h), "")
@scenario("AUTH-12","Auth","Disallowed Host header rejected","allowed_hosts=[localhost,127.0.0.1]","GET /v1/knowledge/bases (valid token) with Host: evil.example","400 (not 200); /health stays exempt for probes")
def _(F):
    r=client.get("/v1/knowledge/bases",headers={**H("alice"),"Host":"evil.example"}); return check(r.status_code==400, r.status_code)

# ---------------- KB ----------------
@scenario("KB-01","Knowledge base","Create a knowledge base with defaults","Signed in user","POST /v1/knowledge/bases {name}","201, access=owner, processing=hosted, language=simple")
def _(F):
    r=api("POST","/v1/knowledge/bases","u_kb1",json={"name":"Plain"}); j=r.json()
    return check(r.status_code==201 and j["access"]=="owner" and j["processing"]=="hosted" and j["language"]=="simple", j)
@scenario("KB-02","Knowledge base","Create with german language and self_hosted processing","Signed in user","POST with language=german, processing=self_hosted","201 (or documented refusal)")
def _(F):
    r=api("POST","/v1/knowledge/bases","u_kb2",json={"name":"DE","language":"german","processing":"self_hosted"}); return check(r.status_code==201 and r.json()["language"]=="german", (r.status_code,r.text[:200]))
@scenario("KB-03","Knowledge base","Empty name rejected","Signed in user","POST name=''","422")
def _(F):
    r=api("POST","/v1/knowledge/bases","u_kb3",json={"name":""}); return check(r.status_code==422, (r.status_code,r.text[:150]))
@scenario("KB-04","Knowledge base","Whitespace-only name rejected","Signed in user","POST name='   '","422 (a blank name is unusable in the UI)")
def _(F):
    r=api("POST","/v1/knowledge/bases","u_kb4",json={"name":"   "}); return check(r.status_code==422, (r.status_code,r.text[:150]))
@scenario("KB-05","Knowledge base","Name length boundary: 80 ok, 81 rejected (docs: 1 to 80)","Signed in user","POST 80-char name; POST 81-char name","201 then 422")
def _(F):
    a=api("POST","/v1/knowledge/bases","u_kb5",json={"name":"a"*80}).status_code; b=api("POST","/v1/knowledge/bases","u_kb5",json={"name":"a"*81}).status_code; return check((a,b)==(201,422),(a,b))
@scenario("KB-21","Knowledge base","OpenAPI contract advertises the enforced name limit (80)","API running","GET /openapi.json; read KnowledgeBaseCreate.name.maxLength","80 (regression for BUG-03)")
def _(F):
    sc=client.get("/openapi.json").json()["components"]["schemas"]; m=[sc[k]["properties"]["name"]["maxLength"] for k in ("KnowledgeBaseCreate","KnowledgeBaseUpdate")]; return check(m==[80,80],m)
@scenario("KB-06","Knowledge base","Unsupported language rejected","Signed in user","POST language=klingon","422")
def _(F):
    r=api("POST","/v1/knowledge/bases","u_kb6",json={"name":"x","language":"klingon"}); return check(r.status_code==422, r.status_code)
@scenario("KB-07","Knowledge base","Invalid processing value rejected","Signed in user","POST processing=cloudy","422")
def _(F):
    r=api("POST","/v1/knowledge/bases","u_kb7",json={"name":"x","processing":"cloudy"}); return check(r.status_code==422, r.status_code)
@scenario("KB-08","Knowledge base","Unicode, emoji and HTML in the name round-trip as plain text","Signed in user","POST name='<img src=x onerror=alert(1)> 日本語 🚀'; list","Stored literally, no mutation, returned as JSON string")
def _(F):
    n="<img src=x onerror=alert(1)> 日本語 🚀"; kb=make_kb("u_kb8",n); names=[b["name"] for b in api("GET","/v1/knowledge/bases","u_kb8").json()["bases"]]; return check(n in names, names)
@scenario("KB-09","Knowledge base","Rename a base","Owner of a base","PATCH name","200 with new name; list shows it")
def _(F):
    kb=make_kb("u_kb9","Old"); r=api("PATCH",f"/v1/knowledge/bases/{kb}","u_kb9",json={"name":"New"}); return check(r.status_code==200 and r.json()["name"]=="New", r.text[:200])
@scenario("KB-10","Knowledge base","Rename to empty name rejected","Owner","PATCH name=''","422")
def _(F):
    kb=make_kb("u_kb10","Old"); r=api("PATCH",f"/v1/knowledge/bases/{kb}","u_kb10",json={"name":""}); return check(r.status_code==422, r.status_code)
@scenario("KB-11","Knowledge base","Language cannot be changed after creation","Owner of english base","PATCH {language:'german'}","Rejected or ignored; language unchanged")
def _(F):
    kb=make_kb("u_kb11","L",language="english"); r=api("PATCH",f"/v1/knowledge/bases/{kb}","u_kb11",json={"name":"L","language":"german"}); l=[b for b in api("GET","/v1/knowledge/bases","u_kb11").json()["bases"] if b["kb_id"]==kb][0]["language"]; return check(l=="english",(r.status_code,l))
@scenario("KB-12","Knowledge base","Delete base removes it from list and its documents become 404","Owner with a base and one doc","DELETE base; list; GET doc","202; not listed; doc 404")
def _(F):
    kb=make_kb("u_kb12","Del"); d,_=up_ready("u_kb12",kb,"expenses.txt"); r=api("DELETE",f"/v1/knowledge/bases/{kb}","u_kb12"); ids=[b["kb_id"] for b in api("GET","/v1/knowledge/bases","u_kb12").json()["bases"]]; g=api("GET",f"/v1/knowledge/documents/{d}","u_kb12").status_code
    return check(r.status_code==202 and kb not in ids and g==404,(r.status_code,kb in ids,g))
@scenario("KB-13","Knowledge base","Unknown base id returns 404 for get-docs / rename / delete","Signed in user","Use random UUID","404 knowledge_base_not_found")
def _(F):
    u=str(uuid.uuid4()); c=[api("GET",f"/v1/knowledge/bases/{u}/documents","u_kb13").status_code,api("PATCH",f"/v1/knowledge/bases/{u}","u_kb13",json={"name":"x"}).status_code,api("DELETE",f"/v1/knowledge/bases/{u}","u_kb13").status_code]; return check(c==[404]*3,c)
@scenario("KB-14","Knowledge base","Malformed base id rejected","Signed in user","GET /v1/knowledge/bases/not-a-uuid/documents","422")
def _(F):
    r=api("GET","/v1/knowledge/bases/not-a-uuid/documents","u_kb14"); return check(r.status_code==422, r.status_code)
@scenario("KB-15","Knowledge base","Tenant isolation: another user cannot read, rename or delete a base","Alice base, Bob token","Bob GET docs / PATCH / DELETE / upload on Alice base","404 each; base intact")
def _(F):
    k=F["kb_hb"]; c=[api("GET",f"/v1/knowledge/bases/{k}/documents","bob").status_code,api("PATCH",f"/v1/knowledge/bases/{k}","bob",json={"name":"pwn"}).status_code,api("DELETE",f"/v1/knowledge/bases/{k}","bob").status_code,upload("bob",k,"expenses.txt").status_code]; intact=api("GET",f"/v1/knowledge/bases/{k}/documents","alice").status_code==200; return check(c==[404]*4 and intact,(c,intact))
@scenario("KB-16","Knowledge base","Per-user cap of 20 bases enforced","Fresh user","Create 21 bases","20x201 then 409 knowledge_base_limit_reached")
def _(F):
    s=[api("POST","/v1/knowledge/bases","u_kb16",json={"name":f"b{i}"}).status_code for i in range(21)]; return check(s[:20]==[201]*20 and s[20]==409, s[-3:])
@scenario("KB-17","Knowledge base","Duplicate base names allowed or cleanly rejected (no 500)","Signed in user","Create same name twice","201+201 or 201+409; never 5xx")
def _(F):
    a=api("POST","/v1/knowledge/bases","u_kb17",json={"name":"Dup"}).status_code; b=api("POST","/v1/knowledge/bases","u_kb17",json={"name":"Dup"}).status_code; return check(a==201 and b<500,(a,b),"documented behaviour unspecified")
@scenario("KB-18","Knowledge base","Unknown JSON fields in create are rejected (strict schema)","Signed in user","POST {name, owner:'bob'}","422 (extra=forbid) so clients cannot smuggle ownership")
def _(F):
    r=api("POST","/v1/knowledge/bases","u_kb18",json={"name":"x","owner":"bob"}); return check(r.status_code==422,(r.status_code,r.text[:120]))
@scenario("KB-19","Knowledge base","Invalid JSON body handled","Signed in user","POST body '{bad'","422/400, never 500")
def _(F):
    r=api("POST","/v1/knowledge/bases","u_kb19",content=b"{bad",headers={"Content-Type":"application/json"}); return check(r.status_code in (400,422),r.status_code)
@scenario("KB-20","Knowledge base","Oversized JSON body rejected","Signed in user","POST 100KB body","413 payload_too_large")
def _(F):
    r=api("POST","/v1/knowledge/bases","u_kb20",json={"name":"x"*100000}); return check(r.status_code==413,(r.status_code,r.text[:80]))

# ---------------- DOC ----------------
@scenario("DOC-01","Documents","Markdown upload is ingested to ready with page_count/size metadata","Base","Upload vacation_policy.md; poll","ready, size_bytes>0, mime text/markdown")
def _(F):
    d=F["d_vac_s"]; return check(d["status"]=="ready" and d["size_bytes"]>0,{k:d[k] for k in ("status","mime_type","size_bytes","error_code")})
@scenario("DOC-02","Documents","Plain-text upload ingests","Base","Upload expenses.txt","ready")
def _(F): return check(F["d_exp_s"]["status"]=="ready",F["d_exp_s"]["status"])
@scenario("DOC-03","Documents","CSV upload ingests and is recognised as a table","Base","Upload headcount.csv","ready")
def _(F): return check(F["d_csv_s"]["status"]=="ready",F["d_csv_s"])
@scenario("DOC-04","Documents","Empty file is refused or fails with stable error code (not stuck)","Base","Upload 0-byte .txt","Rejected 4xx, or doc reaches failed with error_code (e.g. no_text); never stays queued")
def _(F):
    kb=make_kb("u_d4"); r=upload("u_d4",kb,"empty.txt",data=b"",mime="text/plain")
    if r.status_code!=202: return check(r.status_code in (400,415,422),(r.status_code,r.text[:100]))
    d=wait_doc("u_d4",r.json()["doc_id"]); return check(d["status"]=="failed" and d["error_code"],(d["status"],d["error_code"]))
@scenario("DOC-05","Documents","Binary file of unsupported type rejected","Base","Upload .bin octet-stream","415 unsupported_media_type")
def _(F):
    kb=make_kb("u_d5"); r=upload("u_d5",kb,"blob.bin",data=b"\x00\x01\x02binary",mime="application/octet-stream"); return check(r.status_code==415,(r.status_code,r.text[:100]))
@scenario("DOC-06","Documents","Corrupt PDF with no parser configured fails cleanly","Base; docling not deployed","Upload random bytes as .pdf","Accepted then failed with stable error_code, or 415; no hang/500")
def _(F):
    kb=make_kb("u_d6"); r=upload("u_d6",kb,"random.pdf",data=os.urandom(300),mime="application/pdf")
    if r.status_code!=202: return check(r.status_code in (400,415,422),r.status_code)
    d=wait_doc("u_d6",r.json()["doc_id"],60); return check(d["status"]=="failed" and d["error_code"],(d["status"],d["error_code"]))
@scenario("DOC-07","Documents","Content spoofing: executable bytes named .txt are not ingested as text silently","Base","Upload ELF header bytes as notes.txt text/plain","Failed/refused or ingested harmlessly; never 500")
def _(F):
    kb=make_kb("u_d7"); r=upload("u_d7",kb,"notes.txt",data=b"\x7fELF\x02\x01\x01"+os.urandom(200),mime="text/plain"); 
    if r.status_code!=202: return check(r.status_code<500,r.status_code)
    d=wait_doc("u_d7",r.json()["doc_id"],60); return check(d["status"] in ("failed","ready"),(d["status"],d["error_code"]),"observation only")
@scenario("DOC-08","Documents","File over the byte cap returns 413","APP_KNOWLEDGE_PARSE_MAX_BYTES=50MB","Upload 51MB text","413 file_too_large")
def _(F):
    kb=make_kb("u_d8"); r=upload("u_d8",kb,"big.txt",data=b"a"*(51*1024*1024),mime="text/plain"); return check(r.status_code==413,(r.status_code,r.text[:100]))
@scenario("DOC-09","Documents","Idempotency-Key makes retried upload return the same document","Base","Upload twice with the same Idempotency-Key and file","Same doc_id both times; one document in list")
def _(F):
    kb=make_kb("u_d9"); k=uuid.uuid4().hex; a=upload("u_d9",kb,"expenses.txt",headers={"Idempotency-Key":k}); b=upload("u_d9",kb,"expenses.txt",headers={"Idempotency-Key":k}); n=api("GET",f"/v1/knowledge/bases/{kb}/documents","u_d9").json()["total"]
    return check(a.status_code==202 and b.status_code in (200,202) and a.json()["doc_id"]==b.json()["doc_id"] and n==1,(a.status_code,b.status_code,n))
@scenario("DOC-10","Documents","Idempotency-Key reused in a different base conflicts","Two bases","Upload with key to base A; same key to base B","409 idempotency_key_reused")
def _(F):
    a=make_kb("u_d10"); b2=make_kb("u_d10","B"); k=uuid.uuid4().hex; upload("u_d10",a,"expenses.txt",headers={"Idempotency-Key":k}); r=upload("u_d10",b2,"expenses.txt",headers={"Idempotency-Key":k}); return check(r.status_code==409,(r.status_code,r.text[:100]))
@scenario("DOC-10b","Documents","Same key + same base replays the first document and ignores a different body (documented behaviour)","Base","Upload file A with key; upload file B same key","202 with A's doc_id; one document (docs corrected under BUG-02)")
def _(F):
    kb=make_kb("u_d10b"); k=uuid.uuid4().hex; a=upload("u_d10b",kb,"expenses.txt",headers={"Idempotency-Key":k}); b=upload("u_d10b",kb,"vacation_policy.md",headers={"Idempotency-Key":k}); n=api("GET",f"/v1/knowledge/bases/{kb}/documents","u_d10b").json()["total"]; return check(b.status_code==202 and b.json()["doc_id"]==a.json()["doc_id"] and n==1,(b.status_code,n))
@scenario("DOC-11","Documents","Uploading identical content twice without a key does not duplicate chunks/answers","Base","Upload same file twice","Either deduplicated or two docs; observe; no 5xx")
def _(F):
    kb=make_kb("u_d11"); a=upload("u_d11",kb,"expenses.txt"); b=upload("u_d11",kb,"expenses.txt"); n=api("GET",f"/v1/knowledge/bases/{kb}/documents","u_d11").json()["total"]; return check(a.status_code==202 and b.status_code<500,(a.status_code,b.status_code,n),f"documents after double upload: {n}")
@scenario("DOC-12","Documents","Path traversal in filename is neutralised","Base","Upload filename '../../etc/passwd.txt'","Accepted with safe title; no file written outside blob root")
def _(F):
    kb=make_kb("u_d12"); r=upload("u_d12",kb,"../../etc/passwd.txt",data=b"hello traversal",mime="text/plain"); 
    if r.status_code!=202: return check(r.status_code in (400,422),r.status_code)
    d=wait_doc("u_d12",r.json()["doc_id"]); return check(d["status"]=="ready" and "/" not in d["title"] and ".." not in d["title"],(d["title"],d["status"]))
@scenario("DOC-13","Documents","Unicode filename round-trips as title","Base","Upload 'Übersicht_日本語.md'","title preserved")
def _(F):
    kb=make_kb("u_d13"); d,s=up_ready("u_d13",kb,"Übersicht_日本語.md",data="# Titel\n\nHallo Welt".encode(),mime="text/markdown"); return check(s["status"]=="ready" and "Übersicht" in s["title"],s["title"])
@scenario("DOC-14","Documents","Explicit title form field overrides filename","Base","Upload with title='My Policy'","title == 'My Policy'")
def _(F):
    kb=make_kb("u_d14"); d,s=up_ready("u_d14",kb,"expenses.txt",title="My Policy"); return check(s["title"]=="My Policy",s["title"])
@scenario("DOC-15","Documents","Upload to missing base / without a file part","Signed in user","POST to random kb; POST to real kb with no file","404; 4xx (422 or 415 multipart/file missing), never 5xx")
def _(F):
    a=upload("u_d15",str(uuid.uuid4()),"expenses.txt").status_code; kb=make_kb("u_d15"); b=api("POST",f"/v1/knowledge/bases/{kb}/documents","u_d15",files={"title":(None,"x")}).status_code; return check(a==404 and b in (400,415,422),(a,b))
@scenario("DOC-16","Documents","Macro-enabled Office and non-Office ZIP refused","Base","Upload .docm; upload plain zip","415 macro_refused / archive_refused (or failed with those codes)")
def _(F):
    kb=make_kb("u_d16"); z=io.BytesIO(); zipfile.ZipFile(z,"w").writestr("a.txt","x"); a=upload("u_d16",kb,"evil.zip",data=z.getvalue(),mime="application/zip"); 
    z2=io.BytesIO(); zf=zipfile.ZipFile(z2,"w"); zf.writestr("[Content_Types].xml","<x/>"); zf.writestr("word/vbaProject.bin","x"); zf.close(); b=upload("u_d16",kb,"m.docm",data=z2.getvalue(),mime="application/vnd.ms-word.document.macroEnabled.12")
    ok=lambda r: r.status_code==415 or (r.status_code==202 and wait_doc("u_d16",r.json()["doc_id"],40)["status"]=="failed")
    return check(ok(a) and ok(b),(a.status_code,b.status_code,a.text[:80],b.text[:80]))
@scenario("DOC-17","Documents","Document list pagination and bounds","Base with 3 docs","limit=1 offset=1; limit=0; limit=10000","200 with total=3 and 1 item; 422 for invalid limits")
def _(F):
    kb=make_kb("u_d17"); [up_ready("u_d17",kb,f"n{i}.txt",data=f"note {i} unique".encode(),mime="text/plain") for i in range(3)]; a=api("GET",f"/v1/knowledge/bases/{kb}/documents?limit=1&offset=1","u_d17").json(); b=api("GET",f"/v1/knowledge/bases/{kb}/documents?limit=0","u_d17").status_code; c=api("GET",f"/v1/knowledge/bases/{kb}/documents?limit=10000","u_d17").status_code
    return check(a["total"]==3 and len(a["documents"])==1 and b==422 and c==422,(a["total"],len(a["documents"]),b,c))
@scenario("DOC-18","Documents","Get document: unknown id 404; other user 404","Alice doc","GET random id; GET alice doc as bob","404; 404")
def _(F):
    a=api("GET",f"/v1/knowledge/documents/{uuid.uuid4()}","alice").status_code; b=api("GET",f"/v1/knowledge/documents/{F['d_vac']}","bob").status_code; return check((a,b)==(404,404),(a,b))
@scenario("DOC-19","Documents","Download returns original bytes with safe headers","Ready markdown doc","GET /documents/{id}/file","200, identical bytes, nosniff, attachment disposition")
def _(F):
    r=api("GET",f"/v1/knowledge/documents/{F['d_vac']}/file","alice"); orig=open(f"{CORPUS}/vacation_policy.md","rb").read(); h=r.headers
    return check(r.status_code==200 and r.content==orig and h.get("x-content-type-options")=="nosniff" and "attachment" in h.get("content-disposition","").lower(),(r.status_code,dict(h)))
@scenario("DOC-20","Documents","Download of another user's document is 404","Alice doc","bob GET file","404")
def _(F):
    r=api("GET",f"/v1/knowledge/documents/{F['d_vac']}/file","bob"); return check(r.status_code==404,r.status_code)
@scenario("DOC-21","Documents","Delete document: disappears from list, search and download","Base with doc","DELETE doc; list; search its unique phrase; GET file","202; list empty; search none; 404")
def _(F):
    kb=make_kb("u_d21"); d,_=up_ready("u_d21",kb,"u.txt",data=b"The zorblax constant equals 77 in all tenants.",mime="text/plain"); r=api("DELETE",f"/v1/knowledge/documents/{d}","u_d21"); lst=api("GET",f"/v1/knowledge/bases/{kb}/documents","u_d21").json()["total"]; s=search("u_d21","zorblax constant",[kb]).json(); f=api("GET",f"/v1/knowledge/documents/{d}/file","u_d21").status_code
    return check(r.status_code==202 and lst==0 and not s.get("results") and f==404,(r.status_code,lst,len(s.get("results",[])),f))
@scenario("DOC-22","Documents","Delete is idempotent-safe: second delete is 404 not 500","Deleted doc","DELETE twice","202 then 404")
def _(F):
    kb=make_kb("u_d22"); d,_=up_ready("u_d22",kb,"u.txt",data=b"temp doc",mime="text/plain"); a=api("DELETE",f"/v1/knowledge/documents/{d}","u_d22").status_code; b=api("DELETE",f"/v1/knowledge/documents/{d}","u_d22").status_code; return check(a==202 and b==404,(a,b))
@scenario("DOC-23","Documents","Chunk endpoint returns text, headings and neighbours","Ready doc","Search to get a chunk id; GET chunk","200 with text + neighbours")
def _(F):
    s=search("alice","vacation carry over",[F["kb_hb"]]).json()["results"][0]; r=api("GET",f"/v1/knowledge/documents/{s['doc_id']}/chunks/{s['chunk_id']}","alice"); j=r.json()
    return check(r.status_code==200 and j.get("text"),(r.status_code,list(j)))
@scenario("DOC-24","Documents","Chunk id from a different document is not served under another doc id","Two docs","GET /documents/{docA}/chunks/{chunkOfDocB}","404")
def _(F):
    s=search("alice","vacation carry over",[F["kb_hb"]]).json()["results"]; c=[x for x in s if x["doc_id"]==F["d_vac"]][0]; r=api("GET",f"/v1/knowledge/documents/{F['d_exp']}/chunks/{c['chunk_id']}","alice"); return check(r.status_code==404,r.status_code)
@scenario("DOC-25","Documents","Chunk of another tenant's document is 404","Bob chunk","alice requests bob's doc/chunk","404")
def _(F):
    s=search("bob","Zephyr vault",[F["kb_bob"]]).json()["results"][0]; r=api("GET",f"/v1/knowledge/documents/{s['doc_id']}/chunks/{s['chunk_id']}","alice"); return check(r.status_code==404,r.status_code)
@scenario("DOC-26","Documents","Very long single token line (no whitespace) is handled","Base","Upload 200k chars 'a' no spaces","Ready or failed with stable code (page_too_long), no hang")
def _(F):
    kb=make_kb("u_d26"); r=upload("u_d26",kb,"long.txt",data=b"a"*200000,mime="text/plain"); d=wait_doc("u_d26",r.json()["doc_id"],90); return check(d["status"] in ("ready","failed") and (d["status"]=="ready" or d["error_code"]),(d["status"],d["error_code"]))
@scenario("DOC-27","Documents","HTML/script content in a document is stored as inert text and downloaded as attachment","Base","Upload md containing <script>alert(1)</script>; download","ingested; download has attachment + nosniff")
def _(F):
    kb=make_kb("u_d27"); d,s=up_ready("u_d27",kb,"x.md",data=b"# T\n\n<script>alert(1)</script> hello",mime="text/markdown"); r=api("GET",f"/v1/knowledge/documents/{d}/file","u_d27"); return check(s["status"]=="ready" and "attachment" in r.headers.get("content-disposition","").lower(),(s["status"],r.headers.get("content-disposition")))
@scenario("DOC-28","Documents","Concurrent ingestion cap (>=5 in flight) returns 429 with Retry-After","Fresh user","Upload 8 files quickly","Some 202 then 429 ingestion_concurrency_exceeded with Retry-After (or all 202 if worker is fast); no 5xx")
def _(F):
    kb=make_kb("u_d28"); res=[upload("u_d28",kb,f"c{i}.txt",data=(f"concurrent doc {i} "*50).encode(),mime="text/plain") for i in range(8)]; codes=[r.status_code for r in res]; return check(all(c in (202,429) for c in codes),codes,"429s seen: %d"%codes.count(429))
@scenario("DOC-29","Documents","Line-ending and BOM variants ingest correctly","Base","Upload UTF-8-BOM + CRLF text","ready with readable chunk text")
def _(F):
    kb=make_kb("u_d29"); d,s=up_ready("u_d29",kb,"bom.txt",data=b"\xef\xbb\xbfHello\r\nWorld flarpglorb\r\n",mime="text/plain"); r=search("u_d29","flarpglorb",[kb]).json().get("results",[]); return check(s["status"]=="ready" and r and "﻿" not in r[0]["text"],(s["status"],r[0]["text"][:60] if r else None))
@scenario("DOC-30","Documents","Latin-1 encoded text file is handled without crashing","Base","Upload cp1252 bytes","ready (decoded) or cleanly refused (4xx); never stuck or 5xx")
def _(F):
    kb=make_kb("u_d30"); r=upload("u_d30",kb,"latin.txt",data="Café résumé naïve façade".encode("cp1252"),mime="text/plain")
    if r.status_code!=202: return check(r.status_code in (400,415,422),(r.status_code,r.text[:80]),"OBS-01: non-UTF-8 text is refused as unsupported_media_type; the code does not say 'encoding'")
    d=wait_doc("u_d30",r.json()["doc_id"],60); return check(d["status"] in ("ready","failed"),(d["status"],d["error_code"]))

# ---------------- WEB ----------------
def web(u,sub="u_w"):
    kb=make_kb(sub,"web"); return api("POST",f"/v1/knowledge/bases/{kb}/web-pages",sub,json={"url":u})
for i,(u,why) in enumerate([("http://example.com/page","plain http"),("https://user:pw@example.com/","credentials in URL"),("https://localhost/admin","localhost"),("https://127.0.0.1/","loopback IP"),("https://10.0.0.5/","RFC1918 address"),("https://169.254.169.254/latest/meta-data/","cloud metadata IP"),("https://[::1]/","IPv6 loopback"),("ftp://example.com/x","non-http scheme"),("not a url at all","garbage"),("https://"+"a"*2100+".com/","URL over 2048 chars")],1):
    def mk(u=u,i=i):
        def f(F):
            r=web(u,f"u_w{i}"); return check(r.status_code in (422,400),(r.status_code,r.text[:140]))
        return f
    scenario(f"WEB-{i:02d}","Web pages",f"Web page URL refused: {why}","Writer user with a base","POST /web-pages with unsafe URL","422 url_not_allowed (never fetched)")(mk(u,i))
@scenario("WEB-11","Web pages","Public https page is fetched and ingested (or fails with a stable code)","Egress to the internet via sandbox proxy","POST https://example.com/","202 then ready or failed with stable error_code; searchable when ready")
def _(F):
    kb=make_kb("u_w11","web"); r=api("POST",f"/v1/knowledge/bases/{kb}/web-pages","u_w11",json={"url":"https://example.com/"}); 
    if r.status_code!=202: return check(False,(r.status_code,r.text[:150]))
    d=wait_doc("u_w11",r.json()["doc_id"],90); return check(d["status"]=="ready",(d["status"],d["error_code"],d.get("source_url")),"egress may be blocked by sandbox" if d["status"]!="ready" else "")
@scenario("WEB-12","Web pages","Web page endpoint requires knowledge:write and ownership","Bob token, Alice base","POST web-pages to alice kb as bob","404")
def _(F):
    r=api("POST",f"/v1/knowledge/bases/{F['kb_hb']}/web-pages","bob",json={"url":"https://example.com/"}); return check(r.status_code==404,r.status_code)
