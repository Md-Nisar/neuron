# Findings Detail: Confirmed Vulnerabilities

## [CF-SEC-01] Missing SPA Routing and Edge Security Headers on Cloudflare Pages
- **Fingerprint**: `CF-SEC-01`
- **Severity**: Medium (Impact: Medium, Likelihood: Medium)
- **Confidence**: High
- **Boundary**: Edge Proxy to Browser Client
- **Trace**:
  1. Entrypoint: `web/public/_redirects:1` (Cloudflare Pages routing engine)
  2. Sink: `web/public/_headers:1` (Edge HTTP response headers)
- **Evidence**:
  - `web/public/_headers:1`: Security headers definition
  - `web/public/_redirects:1`: SPA fallback rewrite definition
- **Observed Result**:
  Without `_redirects`, deep route reloads return 404; without `_headers`, Cloudflare Pages edge responses omit modern framing and MIME sniffing protections.
- **Remediation**:
  Created `web/public/_redirects` and `web/public/_headers` with strict security headers.

---

## [CF-SEC-02] Reverse Proxy IP Resolution Ignored CF-Connecting-IP Behind Trusted Proxy
- **Fingerprint**: `CF-SEC-02`
- **Severity**: Low (Impact: Low, Likelihood: Low)
- **Confidence**: High
- **Boundary**: Edge Proxy to API Application
- **Trace**:
  1. Entrypoint: `src/neuron_agent/api/main.py:492` (`_client_ip`)
  2. Propagation: `src/neuron_agent/api/main.py:497` (`_trusted_proxy`)
  3. Sink: `src/neuron_agent/api/main.py:504` (Rate limiting client key)
- **Evidence**:
  - `src/neuron_agent/api/main.py:498-506`
  - `tests/security/test_rate_limit_keys.py:215-248`
- **Observed Result**:
  Prior to remediation, `_client_ip` relied solely on `X-Forwarded-For`, potentially causing rate limiting misattribution behind Cloudflare edge proxies.
- **Remediation**:
  Updated `_client_ip` to inspect and normalize `CF-Connecting-IP` when peer is within `trusted_proxies`.
