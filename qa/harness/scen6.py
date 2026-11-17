from lib import *
def _csv(sub, name, data):
    kb=make_kb(sub,"Tables"); d,s=up_ready(sub,kb,name,data=data,mime="text/csv"); return kb,d,s
def _ans(kb,sub,q):
    r=ask(sub,q,[kb]); return (r.json().get("answer","") if r.status_code==200 else r.text), (r.json() if r.status_code==200 else {})
norm=lambda t: t.replace(",","").replace(" ","").replace(" ","").replace(" ","")
@scenario("TAB-01","Tables","Semicolon-delimited CSV (European export) is parsed into columns","Base","Upload ';' CSV; ask for the city with the highest revenue","Correct city; table recognised (citation.table present or answer correct)")
def _(F):
    kb,d,s=_csv("u_t1","eu.csv","stadt;umsatz;mitarbeiter\nBerlin;1200;30\nMünchen;2400;55\nHamburg;900;18\n".encode()); t,j=_ans(kb,"u_t1","Which city has the highest umsatz in the table, and what is it?"); return check("München" in t and "2400" in norm(t),(s["status"],t[:200]))
@scenario("TAB-02","Tables","Quoted commas and thousands separators survive parsing","Base","CSV with \"Berlin, DE\" and \"1,250\"; ask the value for Berlin, DE","1250 (not misaligned)")
def _(F):
    kb,d,s=_csv("u_t2","q.csv",'office,headcount\n"Berlin, DE","1,250"\n"Paris, FR","980"\n'.encode()); t,j=_ans(kb,"u_t2","What is the headcount of the Berlin, DE office?"); return check("1250" in norm(t) or "1,250" in t,(s["status"],t[:200]))
@scenario("TAB-03","Tables","Aggregation over a 1,500-row table is computed, not guessed","Base","Upload 1500-row CSV; ask sum of amount for region EAST","Exact sum (computed via query_table)")
def _(F):
    import random; random.seed(7); rows=[]; tot=0
    for i in range(1500):
        reg=random.choice(["EAST","WEST","NORTH"]); amt=random.randint(10,999); rows.append(f"{i},{reg},{amt}"); tot+= amt if reg=="EAST" else 0
    kb,d,s=_csv("u_t3","orders.csv",("id,region,amount\n"+"\n".join(rows)+"\n").encode()); t,j=_ans(kb,"u_t3","What is the total amount for region EAST in the orders table?"); return check(str(tot) in norm(t),(s["status"],tot,t[:200],j.get("used_tools")))
@scenario("TAB-04","Tables","Empty cells and duplicate headers do not break ingestion","Base","CSV with blank cells and two columns named 'score'","ready or clean failure; never stuck")
def _(F):
    kb=make_kb("u_t4"); r=upload("u_t4",kb,"d.csv",data=b"name,score,score\nAnn,10,\nBob,,20\n,,\n",mime="text/csv"); d=wait_doc("u_t4",r.json()["doc_id"],60) if r.status_code==202 else {"status":f"http{r.status_code}","error_code":r.text[:50]}; return check(d["status"] in ("ready","failed") or r.status_code in (415,422),(d["status"],d.get("error_code")))
@scenario("TAB-05","Tables","Cross-tenant: another user's table cannot be queried through the agent","Alice numbers KB","Bob asks about 'Engineering employees' with Alice's numbers kb id","No Alice data")
def _(F):
    r=ask("bob","How many employees does Engineering have in the headcount table?",[F["kb_num"]]); a=r.json().get("answer","") if r.status_code==200 else r.text; return check(not re.search(r"\b48\b",a) and "5200000" not in a.replace(",","") and not r.json().get("citations"),a[:200])
