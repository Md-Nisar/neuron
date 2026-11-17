"""QA harness: the repo's stand-in IdP plus GET /qa/mint?sub=&scope=&roles=&exp=&aud=&iss= (local only)."""
import sys, json, time, uuid
from http.server import ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
sys.path.insert(0, "/home/user/neuron/web/e2e")
import fake_idp as f

class H(f.Handler):
    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/qa/mint":
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            scope = f.PERMISSIONS if q.get("scope") is None else q["scope"]
            claims = {"aud": q.get("aud", f.AUDIENCE), "sub": q["sub"], "scope": scope,
                      "roles": [r for r in q.get("roles", "").split(",") if r], "jti": str(uuid.uuid4())}
            if "iss" in q: claims["iss"] = q["iss"]
            if "exp" in q: claims["exp"] = int(time.time()) + int(q["exp"])
            tok = f._token(claims, {"typ": "at+jwt"})
            return self._send(200, tok.encode(), "text/plain")
        return super().do_GET()

ThreadingHTTPServer(("127.0.0.1", 8180), H).serve_forever()
