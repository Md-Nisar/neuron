import http.server, threading, uuid, os, json, time
seen = []
class H(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("content-length", 0)))
        if self.headers.get("content-encoding") == "zstd":
            try:
                import zstandard; body = zstandard.ZstdDecompressor().stream_reader(body).read()
            except Exception: pass
        seen.append((self.path, body))
        self.send_response(202); self.send_header("content-type", "application/json"); self.end_headers(); self.wfile.write(b"{}")
    def do_GET(self):
        self.send_response(200); self.send_header("content-type", "application/json"); self.end_headers(); self.wfile.write(b"{}")
    def log_message(self, *a): pass
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H); port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ.update(LANGSMITH_ENDPOINT=f"http://127.0.0.1:{port}", LANGSMITH_API_KEY="stub", LANGSMITH_TRACING="true", NO_PROXY="127.0.0.1")
for k in ("HTTPS_PROXY","HTTP_PROXY","https_proxy","http_proxy"): os.environ.pop(k, None)
from langchain_core.runnables import RunnableLambda
from langsmith import Client
rid = uuid.uuid4()
RunnableLambda(lambda x: x).invoke("hi", config={"run_id": rid})
time.sleep(3)
client = Client()
client.create_feedback(str(rid), key="user_score", score=1.0, comment=None, extra={"reason": "helpful"})
client.flush() if hasattr(client, "flush") else None
time.sleep(2)
print("our run id:", rid)
for path, body in seen:
    print(path, len(body), "contains run id:", str(rid).encode() in body)
