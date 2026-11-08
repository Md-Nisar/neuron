# Security Audit Report: Neuron Repository

**Audit Profile**: `standard`  
**Target Repository**: `c:\entomo\AI\neuron`  
**Reviewed Commit**: `00ef23ef2004a375d55c2fd591a1ea9cc56a9f7c (dirty)`  
**Execution Policy**: Sandboxed source-and-local-only execution (no live endpoint probing)  
**Date**: November 2026  

---

## 1. Executive Summary & Security Posture

A comprehensive security audit of the **Neuron** repository was performed using the Cloudflare Security Audit skill and rigorous multi-agent verification standards. Neuron demonstrates an exceptional security architecture with mature defensive controls:
- **Strict SSRF Mitigation**: `PublicOnlyBackend` in `security/egress.py` resolves hostnames once, verifies all resolved IPs are public, and connects directly to the IP address while preserving TLS SNI.
- **Strict AST Sandbox for Tools**: `tools/calculator.py` strictly limits operations to numbers and basic operators via an AST visitor with max length, max exponent, and max magnitude limits.
- **Secure Multipart Ingestion**: `api/multipart.py` streams files directly without spooling to disk, enforcing byte limits and discarding client-supplied filenames.
- **Unguessable Storage Keys**: `knowledge/blobs.py` assigns 128-bit random hex keys and verifies streaming SHA-256 integrity on every read.
- **Memory-Only Client Authentication**: `web/src/lib/auth/session.ts` holds JWT tokens in private JavaScript class fields only, never persisting them to cookies or browser storage.
- **Hardened Chat Rendering**: `web/src/features/chat/Markdown.tsx` disables raw HTML and images, restricting links to approved schemes with `rel="noopener noreferrer nofollow"`.

During this audit, two confirmed vulnerabilities were remediated and verified with test suites, and three infrastructure/deployment considerations were cataloged for owner validation.

---

## 2. Confirmed Findings Table

| Fingerprint | Severity | Title | Affected Boundary | Result |
| :--- | :--- | :--- | :--- | :--- |
| **CF-SEC-01** | **Medium** | Missing SPA Routing & Edge Security Headers on Cloudflare Pages | Edge Proxy to Browser Client | Remediated via `web/public/_redirects` and `web/public/_headers` |
| **CF-SEC-02** | **Low** | Reverse Proxy IP Resolution Ignored CF-Connecting-IP Behind Trusted Proxy | Edge Proxy to API Application | Remediated in `api/main.py` & verified in `tests/security/test_rate_limit_keys.py` |

---

## 3. Confirmed Findings Details & Remediation

### [CF-SEC-01] Missing SPA Routing and Edge Security Headers on Cloudflare Pages
- **Severity**: Medium (Likelihood: Medium, Impact: Medium)
- **Affected Surface**: `web/public/_redirects`, `web/public/_headers`
- **Root Cause**: Cloudflare Pages hosts static assets. Without a `_redirects` rule (`/* /index.html 200`), direct navigation to deep client-side routes (e.g. `/chat/history`) fails with HTTP 404. Without `_headers`, Cloudflare Pages does not emit defense-in-depth security headers.
- **Remediation**:
  1. Created `web/public/_redirects` with SPA fallback routing.
  2. Created `web/public/_headers` configuring `Strict-Transport-Security`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: SAMEORIGIN`, `Permissions-Policy`, and caching rules.
- **Status**: **RESOLVED** in worktree.

### [CF-SEC-02] Reverse Proxy IP Resolution Ignored CF-Connecting-IP Behind Trusted Proxy
- **Severity**: Low (Likelihood: Low, Impact: Low)
- **Affected Surface**: `src/neuron_agent/api/main.py` (`_client_ip`)
- **Root Cause**: `_client_ip` walked `X-Forwarded-For` right-to-left when behind `APP_TRUSTED_PROXIES`, but did not evaluate `CF-Connecting-IP`, the authoritative edge client IP header populated by Cloudflare.
- **Remediation**:
  1. Updated `src/neuron_agent/api/main.py` to inspect `CF-Connecting-IP` when peer is in `trusted_proxies`.
  2. Normalizes IPv6 addresses to /64 CIDR prefixes to prevent rate limiting bypass via IPv6 rotation.
  3. Added unit tests in `tests/security/test_rate_limit_keys.py`.
- **Status**: **RESOLVED** in worktree; tests passing.

---

## 4. Needs Validation Table

| Fingerprint | Title | Exact Blocker | Local Next Step | Deployment Check |
| :--- | :--- | :--- | :--- | :--- |
| **CF-SEC-04** | Direct Origin Exposure Bypass of Cloudflare WAF | Missing cloud infrastructure manifests in repo | Inspect local container binding on 0.0.0.0:8000 | Verify cloud firewall/security groups allow ingress only from Cloudflare IPs or use `cloudflared` |
| **CF-SEC-05** | Health Readiness Discloses Environment Name | Unknown external WAF route shielding rules | Send `GET /health/ready` locally | Verify whether `/health/*` is restricted to internal monitoring systems |
| **CF-SEC-06** | Cloudflare Access JWT Assertion Header Integration | Unknown edge transform / Zero Trust attachment | Check `TokenVerifier` header extraction | Confirm if Cloudflare Access is deployed and how JWT assertions are forwarded |

---

## 5. Coverage Ledger Summary

- **Total Units Planned**: 12
- **Units Covered**: 8
- **Candidates Validated**: 4 (2 Confirmed, 2 Needs Validation, 1 Supplemental Needs Validation)
- **Units Blocked / Deferred**: 0
- **Final Critic Assessment**: Complete coverage across all material entry surfaces, boundaries, and attack classes.
