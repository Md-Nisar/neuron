# Needs Validation Items

These items are source-grounded candidates whose definitive verification depends on external infrastructure, cloud configuration, or deployment facts not present in repository source.

---

### [CF-SEC-04] Direct Origin Exposure Bypass of Cloudflare Edge / WAF
- **Fingerprint**: `CF-SEC-04`
- **Boundary**: Public Internet to Origin Container
- **Source Trace**:
  - `Dockerfile:60`: `EXPOSE 8000`
  - `src/neuron_agent/api/main.py:550`: Uvicorn HTTP listener
- **Exact Blocker**:
  Repository does not contain cloud infrastructure configurations (Terraform, CloudFormation, AWS Security Groups) establishing whether origin port 8000 is open to the public internet.
- **Local Validation Plan**:
  Run Docker container locally and inspect network socket binding.
- **Owner Deployment Plan**:
  Infrastructure operator should confirm that public traffic can reach the application origin ONLY via Cloudflare IP addresses or through a Cloudflare Tunnel (`cloudflared`).

---

### [CF-SEC-05] Unauthenticated Health Readiness Endpoint Exposes Deployment Environment Name
- **Fingerprint**: `CF-SEC-05`
- **Boundary**: Unauthenticated Caller to Health Endpoint
- **Source Trace**:
  - `src/neuron_agent/api/main.py:230-245` (`GET /health/ready`)
- **Exact Blocker**:
  Source does not indicate whether Cloudflare WAF Transform Rules or API Gateway shields `/health/*` from public external callers.
- **Local Validation Plan**:
  Send `GET /health/ready` locally to observe response body: `{"status": "ready", "environment": "dev"}`.
- **Owner Deployment Plan**:
  Verify whether production deployment shields `/health/*` at Cloudflare WAF or if environment name should be omitted from unauthenticated responses in production.

---

### [CF-SEC-06] Cloudflare Access JWT Assertion Header Integration
- **Fingerprint**: `CF-SEC-06`
- **Boundary**: Zero Trust Edge to API Origin
- **Source Trace**:
  - `src/neuron_agent/security/auth.py:120-140` (`TokenVerifier`)
- **Exact Blocker**:
  Repository does not specify whether Cloudflare Zero Trust Access is deployed or if a Cloudflare Worker transforms the `Cf-Access-Jwt-Assertion` header into `Authorization: Bearer`.
- **Local Validation Plan**:
  Review `TokenVerifier` header extraction logic with test headers.
- **Owner Deployment Plan**:
  Zero Trust administrator confirms whether Cloudflare Access is attached to API endpoints and how the JWT assertion is forwarded.
