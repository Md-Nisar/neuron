"""DG-00.04: create Auto Ontology's service account and its API token, and enable semantic
compilation (A1).

The service account is a viewer, invited by the bootstrap admin. Auto Ontology's MCP server takes no
service credential by design, so the "service credential" is this viewer's API token, sent as
x-api-key to the /api routes the MCP tools wrap. Secrets are read from and written to AO_LOCAL_ENV
(a file outside the repository), never printed.

  AO_LOCAL_ENV=... python service_account.py http://127.0.0.1:3000
"""
import http.cookiejar
import json
import os
import secrets
import sys
import urllib.request

BASE = sys.argv[1]
ENV_FILE = os.environ["AO_LOCAL_ENV"]
SVC_EMAIL = "svc-neuron-gateway@example.test"


def opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                       urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def call(op, method: str, path: str, body=None, headers=None):
    req = urllib.request.Request(BASE + path, method=method,
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Origin": BASE, **(headers or {})})
    with op.open(req) as r:
        text = r.read().decode()
        return json.loads(text) if text else None


def sign_in(email: str, password: str):
    op = opener()
    call(op, "POST", "/api/auth/sign-in/email", {"email": email, "password": password})
    return op


def main() -> None:
    env = dict(line.split("=", 1) for line in open(ENV_FILE).read().split())
    admin = sign_in(os.environ["AUTO_ONTOLOGY_ADMIN_EMAIL"], env["AUTO_ONTOLOGY_ADMIN_PASSWORD"])
    if "SVC_PASSWORD" not in env:
        env["SVC_PASSWORD"] = secrets.token_hex(16)
        invite = call(admin, "POST", "/api/invitations", {"email": SVC_EMAIL, "name": "Neuron gateway (spike)", "role": "viewer"})
        token = invite["url"].rstrip("/").rsplit("/", 1)[-1]
        call(opener(), "POST", f"/api/invitations/{token}/accept", {"password": env["SVC_PASSWORD"]})
    svc = sign_in(SVC_EMAIL, env["SVC_PASSWORD"])
    if "AO_API_TOKEN" not in env:
        minted = call(svc, "POST", "/api/api-tokens", {"name": "dg-00.04"})
        env["AO_API_TOKEN"] = minted.get("token") or minted.get("key")
    with open(ENV_FILE, "w") as f:
        f.write("".join(f"{k}={v}\n" for k, v in env.items()))
    print("semantic compilation:", call(admin, "PUT", "/api/configurations/semantic-compilation", {"enabled": True}))
    me = call(opener(), "GET", "/api/terms", headers={"x-api-key": env["AO_API_TOKEN"]})
    print("service token works on /api/terms:", isinstance(me, (list, dict)))


if __name__ == "__main__":
    main()
