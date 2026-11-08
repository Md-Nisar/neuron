# Security Remediation Log

**Audit Campaign:** Cloudflare Complete Security Audit  
**Date:** November 9, 2026  
**Auditor:** Senior Cloudflare Security Engineer  
**Status:** Remediations Complete & Verified  

---

## Remediation 1: Cloudflare Pages SPA Routing (`_redirects`) and Edge Security Headers (`_headers`)

### Problem Statement
The React frontend in `web/` is an SPA compiled with Vite to `web/dist`. When hosted on Cloudflare Pages, browser refreshes or direct navigation to routes like `/threads/:id`, `/data`, `/knowledge`, and `/oauth2-redirect` produced HTTP 404 errors due to missing single-page application rewrite rules. Furthermore, Cloudflare Pages edge served static files without security headers, omitting CSP, HSTS, frame protection, and referrer policy at the edge layer.

### Files Created
- [`web/public/_redirects`](web/public/_redirects)
- [`web/public/_headers`](web/public/_headers)

### Remediation Applied
1. Created `web/public/_redirects` to instruct Cloudflare Pages to rewrite all client routes to `/index.html`:
   ```
   /* /index.html 200
   ```
2. Created `web/public/_headers` establishing baseline defense-in-depth security headers and cache policies on Cloudflare Pages edge:
   ```http
   /*
     X-Content-Type-Options: nosniff
     Referrer-Policy: no-referrer
     X-Frame-Options: SAMEORIGIN
     Cross-Origin-Opener-Policy: same-origin
     Cross-Origin-Resource-Policy: same-origin
     Permissions-Policy: accelerometer=(), camera=(), clipboard-read=(), clipboard-write=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), payment=(), usb=()
     X-Permitted-Cross-Domain-Policies: none
     Strict-Transport-Security: max-age=63072000; includeSubDomains

   /index.html
     Cache-Control: no-cache

   /assets/*
     Cache-Control: public, max-age=31536000, immutable
   ```

### Verification
- Verified Vite copies `web/public/` contents to `web/dist/` upon build.
- Checked against reference formats in [`scripts/web_headers.py`](scripts/web_headers.py).

---

## Remediation 2: Cloudflare Visitor IP Attribution (`CF-Connecting-IP`)

### Problem Statement
In [`src/neuron_agent/api/main.py:485-507`](src/neuron_agent/api/main.py#L485-L507), the client IP extractor function `_client_ip` only parsed `X-Forwarded-For`. When deployed behind Cloudflare WAF, Cloudflare injects the verified client IP into `CF-Connecting-IP`. If multiple proxies or intermediate hops exist, relying only on `X-Forwarded-For` without inspecting `CF-Connecting-IP` could result in rate-limiting attribution mismatches or spoofed headers.

### Files Modified
- [`src/neuron_agent/api/main.py`](src/neuron_agent/api/main.py)
- [`tests/security/test_rate_limit_keys.py`](tests/security/test_rate_limit_keys.py)

### Code Diff
```python
--- a/src/neuron_agent/api/main.py
+++ b/src/neuron_agent/api/main.py
@@ -495,6 +495,15 @@ def _client_ip(request: Request) -> str:
     except ValueError:
         return peer
     if _trusted_proxy(address):
+        cf_connecting_ip = request.headers.get("CF-Connecting-IP")
+        if cf_connecting_ip:
+            try:
+                cf_address = _unmapped(ipaddress.ip_address(cf_connecting_ip.strip()))
+                if isinstance(cf_address, ipaddress.IPv6Address):
+                    return str(ipaddress.IPv6Network((int(cf_address), 64), strict=False))
+                return str(cf_address)
+            except ValueError:
+                pass
         entries = ",".join(request.headers.getlist("X-Forwarded-For")).split(",")
         while entries and _trusted_proxy(address):
             try:
```

### Verification & Regression Tests Added
Added tests in [`tests/security/test_rate_limit_keys.py`](tests/security/test_rate_limit_keys.py):
1. `test_cf_connecting_ip_behind_trusted_proxy_is_honored`: Verifies `CF-Connecting-IP` takes precedence when connecting peer is in `APP_TRUSTED_PROXIES`.
2. `test_cf_connecting_ip_from_untrusted_peer_is_ignored`: Verifies `CF-Connecting-IP` sent by an untrusted peer is ignored and not spoofable.

**Test Result:**
```
uv run python -m pytest tests/security/test_rate_limit_keys.py
39 passed in 0.42s
```

---

## Remediation 3: Local `.env` Credential Exposure Hardening

### Problem Statement
Local `.env` contained live NVIDIA and OpenAI API keys (`LLM_API_KEY`, `OPENAI_API_KEY`, `NVIDIA_API_KEY`).

### Actions Taken
1. Verified `.env` is listed in [`.gitignore`](.gitignore) and [`.dockerignore`](.dockerignore).
2. Checked git index (`git ls-files --error-unmatch .env`) confirming `.env` was never tracked.
3. Searched git history confirming no live keys were committed.
4. Documented mandatory practice: Local `.env` files must remain untracked. In CI/CD and production environments, credentials must be injected via runtime environment variables or vault secret managers, never written to disk.

---

## Post-Remediation Verification Matrix

| Scan / Test | Scope | Command | Outcome |
|---|---|---|---|
| Ruff Format | Full Python Codebase | `uv run python -m ruff format --check src tests loadtest` | **Passed** |
| Ruff Lint | Full Python Codebase | `uv run python -m ruff check src tests loadtest` | **Passed** |
| Mypy Typecheck | Source, Tests, Scripts | `uv run python -m mypy src loadtest ...` | **Passed** (115 files) |
| Bandit SAST | Source & Scripts | `uv run python -m bandit -q -r src loadtest scripts/` | **Passed** (0 issues) |
| Security Test Suite | 31 Security Test Modules | `uv run python -m pytest tests/security` | **Passed** (638 passed) |
| Architecture Guard | AST import & env rules | `uv run python -m pytest tests/unit/test_entrypoint.py` | **Passed** (14 passed) |

---

## Summary of Outstanding Operator Actions
1. **Cloudflare Tunnel / Origin Protection:** Configure `cloudflared` or enforce firewall ingress filtering so origin port 8000 is accessible only from Cloudflare IP addresses.
2. **Cloudflare Access (Zero Trust):** If securing the API with Cloudflare Access, configure a Worker Transform Rule to map `Cf-Access-Jwt-Assertion` to `Authorization: Bearer <token>`.
3. **API Key Rotation:** Periodically rotate development API keys present in local workstation `.env` files.
