from lib import *
import subprocess, signal, io

def _xlsx():
    return open(CORPUS+'/sales.xlsx','rb').read()

@scenario("DOC-31","Documents","XLSX workbook is ingested natively (no external parser) and table is queryable","Base; no docling","Upload .xlsx; ask agent for total q2 revenue","ready; agent answers 3250 (1500+1100+650)")
def _(F):
    kb=make_kb("u_x1","Sheets"); r=upload("u_x1",kb,"sales.xlsx",data=_xlsx(),mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"); 
    if r.status_code!=202: return check(False,(r.status_code,r.text[:150]))
    d=wait_doc("u_x1",r.json()["doc_id"],90)
    if d["status"]!="ready": return check(False,(d["status"],d["error_code"]),"xlsx without docling parser")
    a=ask("u_x1","What is the total q2_revenue across all regions in the Sales sheet?",[kb]); t=a.json().get("answer","") if a.status_code==200 else a.text
    return check("3250" in t.replace(",","").replace(".",""),t[:250])
@scenario("DOC-32","Documents","Whitespace-only text file does not become 'ready' with zero content","Base","Upload file of spaces/newlines","failed with error_code no_text (or refused)")
def _(F):
    kb=make_kb("u_x2"); r=upload("u_x2",kb,"blank.txt",data=b"   \n\n\t  \n",mime="text/plain")
    if r.status_code!=202: return check(r.status_code in (400,415,422),(r.status_code,r.text[:100]))
    d=wait_doc("u_x2",r.json()["doc_id"],60); return check(d["status"]=="failed" and d["error_code"],(d["status"],d["error_code"]))
@scenario("DOC-33","Documents","Large multi-chunk document (≈60 KB) ingests and a deep passage is retrievable","Base; live embeddings (batch=1)","Upload 60KB markdown with 40 sections, one holding a unique fact","ready in reasonable time; search finds the deep fact; chunk headings preserved")
def _(F):
    secs=[f"## Section {i}\n\n"+(f"Routine filler paragraph number {i} about quarterly logistics and warehouse staffing. "*12) for i in range(40)]
    secs[27]+="\n\nThe emergency shutdown passphrase for facility 27 is Quokka-Lantern-8841."
    kb=make_kb("u_x3","Big"); t0=time.time(); r=upload("u_x3",kb,"big.md",data=("# Operations Manual\n\n"+"\n\n".join(secs)).encode(),mime="text/markdown"); d=wait_doc("u_x3",r.json()["doc_id"],240); dt=time.time()-t0
    s=search("u_x3","emergency shutdown passphrase facility 27",[kb]).json().get("results",[]) if d["status"]=="ready" else []
    return check(d["status"]=="ready" and s and "Quokka" in s[0]["text"],(d["status"],round(dt,1),s[0]["headings"] if s else None),f"ingest took {dt:.0f}s")
@scenario("DOC-34","Documents","Markdown heading path is stored on chunks","Ready markdown doc","Search; inspect headings","headings contain parent chain e.g. ['Acme Employee Handbook','Vacation Policy']")
def _(F):
    s=search("alice","vacation accrual",[F["kb_hb"]]).json()["results"][0]; return check(s["headings"][-2:]==["Acme Employee Handbook","Vacation Policy"] or s["headings"]==["Acme Employee Handbook","Vacation Policy"],s["headings"])
@scenario("DOC-35","Documents","Markdown table content is searchable","Base","Upload md with a pipe table; search a cell value","Row text returned")
def _(F):
    kb=make_kb("u_x5"); up_ready("u_x5",kb,"t.md",data=b"# Prices\n\n| item | price |\n|---|---|\n| flux capacitor | 1955 eur |\n| hoverboard | 2015 eur |\n",mime="text/markdown"); s=search("u_x5","price of the hoverboard",[kb]).json()["results"]; return check(s and "2015" in s[0]["text"],[x["text"][:80] for x in s])
@scenario("RES-01","Resilience","Worker killed mid-ingestion: document is recovered and reaches ready after the worker restarts","Worker running as a local process","Upload 6 large docs; SIGKILL worker; restart worker; poll","All documents end ready (stalled job reclaimed); none stuck")
def _(F):
    pid=subprocess.run("pgrep -f 'neuron-worker'",shell=True,capture_output=True,text=True).stdout.split()
    if not pid: raise Skip("worker process not found")
    kb=make_kb("u_r1","Crash"); ids=[]
    for i in range(4):
        body=("# Doc %d\n\n"%i)+"\n\n".join(f"## S{j}\n\n"+("crash recovery filler text %d-%d. "%(i,j))*15 for j in range(25))
        r=upload("u_r1",kb,f"c{i}.md",data=body.encode(),mime="text/markdown"); ids.append(r.json()["doc_id"])
    time.sleep(3); subprocess.run("pkill -9 -f 'neuron-worker'",shell=True); time.sleep(2)
    mid=[api("GET",f"/v1/knowledge/documents/{d}","u_r1").json()["status"] for d in ids]
    env="env -i PATH=\"$PATH\" HOME=\"$HOME\" APP_ENV=development APP_POSTGRES_WORKER_DSN='postgresql://neuron_worker:worker-local-only@127.0.0.1:5432/neuron?sslmode=disable' APP_KNOWLEDGE_BLOB_ROOT=/tmp/claude-0/qa/blobs APP_KNOWLEDGE_EMBEDDING_PROVIDER=nvidia NVIDIA_API_KEY=\"$LLM_API_KEY\" APP_KNOWLEDGE_PARSER_URL=http://127.0.0.1:5001 APP_OTEL_ENABLED=false"
    subprocess.Popen(f"cd /home/user/neuron && {env} nohup uv run neuron-worker > /tmp/claude-0/qa/worker2.log 2>&1 &",shell=True)
    t0=time.time(); st=[]
    while time.time()-t0<300:
        st=[api("GET",f"/v1/knowledge/documents/{d}","u_r1").json()["status"] for d in ids]
        if all(s in ("ready","failed") for s in st): break
        time.sleep(3)
    return check(all(s=="ready" for s in st),{"after_kill":mid,"final":st,"recovery_s":round(time.time()-t0)})

# ---------------- Office / PDF through docling-serve ----------------
def _office(sub, name, mime):
    kb = make_kb(sub, "Office"); r = upload(sub, kb, name, mime=mime)
    assert r.status_code == 202, (r.status_code, r.text[:150])
    return kb, r.json()["doc_id"], wait_doc(sub, r.json()["doc_id"], 240)
PDF="application/pdf"; DOCX="application/vnd.openxmlformats-officedocument.wordprocessingml.document"; PPTX="application/vnd.openxmlformats-officedocument.presentationml.presentation"
@scenario("OFF-01","Office/PDF","PDF is parsed with page numbers; deep-page fact is found with page_start=2","docling-serve running","Upload 3-page handbook.pdf; search 'maximum stacking height'","ready, page_count=3, hit from page 2 with page_start=2")
def _(F):
    kb,d,s=_office("u_o1","handbook.pdf",PDF); r=search("u_o1","maximum stacking height forklift",[kb]).json().get("results",[]); return check(s["status"]=="ready" and s["page_count"]==3 and r and r[0]["page_start"]==2,(s["status"],s["page_count"],[(x["page_start"],x["text"][:40]) for x in r[:2]]))
@scenario("OFF-02","Office/PDF","Agent answers from a PDF and the citation carries the correct page","docling-serve; handbook.pdf","Ask who the safety officer is and the budget reserve","Ingrid Solberg (p.2); 8 percent (p.3); citations with page_start 2 and 3")
def _(F):
    kb,d,s=_office("u_o2","handbook.pdf",PDF); a=ask("u_o2","Who is the safety officer on duty, and what percent of the budget is the contingency reserve?",[kb]); j=a.json(); t=j.get("answer",""); pages={c.get("page_start") for c in j.get("citations",[])}
    return check("Solberg" in t and "8" in t and {2,3}<=pages,(t[:240],pages))
@scenario("OFF-03","Office/PDF","DOCX (headings + table) ingests and table cell is findable","docling-serve","Upload policy.docx; search 'per diem Oslo'","ready; Oslo 88 in passage")
def _(F):
    kb,d,s=_office("u_o3","policy.docx",DOCX); r=search("u_o3","Oslo per diem",[kb]).json().get("results",[]); return check(s["status"]=="ready" and r and "88" in " ".join(x["text"] for x in r),(s["status"],[x["text"][:60] for x in r]))
@scenario("OFF-04","Office/PDF","PPTX slide text is searchable","docling-serve","Upload deck.pptx; search 'Orion platform'","ready; hit mentions Q3 2027")
def _(F):
    kb,d,s=_office("u_o4","deck.pptx",PPTX); r=search("u_o4","when does the Orion platform launch",[kb]).json().get("results",[]); return check(s["status"]=="ready" and r and "2027" in r[0]["text"],(s["status"],[x["text"][:60] for x in r]))
@scenario("OFF-05","Office/PDF","Password-protected PDF fails with encrypted_pdf","docling-serve","Upload encrypted.pdf","failed or refused with error_code encrypted_pdf")
def _(F):
    kb=make_kb("u_o5"); r=upload("u_o5",kb,"encrypted.pdf",mime=PDF)
    if r.status_code!=202: return check("encrypted" in r.text,(r.status_code,r.text[:100]))
    s=wait_doc("u_o5",r.json()["doc_id"],120); return check(s["status"]=="failed" and s["error_code"]=="encrypted_pdf",(s["status"],s["error_code"]))
@scenario("OFF-06","Office/PDF","Corrupt PDF with parser present fails with a stable code (no hang, no 500)","docling-serve","Upload random bytes as .pdf","failed with error_code")
def _(F):
    kb=make_kb("u_o6"); r=upload("u_o6",kb,"x.pdf",data=os.urandom(400),mime=PDF); s=wait_doc("u_o6",r.json()["doc_id"],180) if r.status_code==202 else {"status":f"http{r.status_code}","error_code":r.text[:60]}; return check(s["status"]=="failed" and s["error_code"] or r.status_code in (415,422),(s["status"],s["error_code"]))
@scenario("OFF-07","Office/PDF","XLSX ingests and a table question is answered correctly","docling-serve; sales.xlsx","Upload xlsx; ask total q2_revenue","3250")
def _(F):
    kb,d,s=_office("u_o7","sales.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"); a=ask("u_o7","What is the total q2_revenue across all regions in the Sales sheet?",[kb]); t=a.json().get("answer","") if a.status_code==200 else a.text; return check(s["status"]=="ready" and "3250" in t.replace(",","").replace(".",""),(s["status"],t[:250]))
@scenario("OFF-08","Office/PDF","Mismatched type: .docx name with PDF content is judged by content, not name","docling-serve","Upload PDF bytes named fake.docx claiming docx mime","Ingested as PDF or refused; never 500/stuck")
def _(F):
    kb=make_kb("u_o8"); r=upload("u_o8",kb,"fake.docx",data=open(CORPUS+"/handbook.pdf","rb").read(),mime=DOCX)
    if r.status_code!=202: return check(r.status_code in (400,415,422),(r.status_code,r.text[:100]))
    s=wait_doc("u_o8",r.json()["doc_id"],180); return check(s["status"] in ("ready","failed"),(s["status"],s["error_code"],s["mime_type"]),"content sniffed: "+str(s["mime_type"]))
