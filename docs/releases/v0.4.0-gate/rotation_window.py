"""Measure how long a newly published signing key is rejected with default cache settings."""
import asyncio, json, threading, time, uuid
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from neuron_agent.config.settings import Settings
from neuron_agent.security.auth import TokenVerifier
from neuron_agent.errors.base import AuthenticationError

keys = {k: ec.generate_private_key(ec.SECP256R1()) for k in ("k1", "k2")}
published = {"k1"}
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"keys": [{**json.loads(jwt.algorithms.ECAlgorithm.to_jwk(keys[k].public_key())), "kid": k, "alg": "ES256"} for k in published]}).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def log_message(self, *a): pass
server = ThreadingHTTPServer(("127.0.0.1", 8767), H); threading.Thread(target=server.serve_forever, daemon=True).start()
def tok(kid):
    now = datetime.now(UTC)
    return jwt.encode({"iss": "https://i/", "aud": "a", "sub": "s", "iat": now, "nbf": now, "exp": now + timedelta(minutes=5)}, keys[kid], algorithm="ES256", headers={"kid": kid})
settings = Settings(env="development", auth_mode="jwt", auth_issuer="https://i/", auth_audience="a", auth_jwks_url="http://127.0.0.1:8767/jwks.json", identity_hash_key="h" * 32)
print("defaults: cache", settings.auth_jwks_cache_seconds, "s")
verifier = TokenVerifier(settings)
async def main():
    await verifier.verify("Bearer " + tok("k1"))           # first fetch, t=0
    published.add("k2"); start = time.monotonic()
    while True:
        try:
            await verifier.verify("Bearer " + tok("k2")); break
        except AuthenticationError:
            await asyncio.sleep(1)
    print(f"k2 accepted {time.monotonic() - start:.1f}s after publication (first fetch at t=0)")
asyncio.run(main())
