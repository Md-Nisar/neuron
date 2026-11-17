# Security report: whole application, round 1

Date 2026-11-17. Target: neuron v1.4.0 plus this branch. Test cases with their results in each cycle: `security_test_scenarios.json` / `.csv` (71 scenarios).

This is an authorized assessment of a local stack, not a certification. It combines automated scans with manual, non-destructive penetration tests. A clean result means the listed attacks failed. It does not mean that no vulnerability is left.

## 1. Verdict

**The application held against almost every attack that was tried. The test found one real cross-user weakness and two weak identity-provider settings, fixed all three and retested them.**

| Question | Answer, with the evidence |
|---|---|
| Can an unauthorized user reach protected resources? | **No.** All 30 `/v1` routes answer 401 without a valid token (AUTH-01). Forged tokens were all refused: `alg=none`, HS256 signed with the public key, an attacker's RSA key with the real `kid`, a tampered payload, a master-realm admin token and an expired token (AUTH-02 to -05). Failed authentication is rate-limited, including with a spoofed `X-Forwarded-For` (AUTH-07, CFG-04). |
| Can one user reach another user's knowledge or documents? | **Not directly. In cycle 1 a user could push content into everyone else's searches; this is now fixed.** Direct access by id gave 404 everywhere: bases, documents, chunks, files, threads, approvals, feedback, memories, export, search with a foreign `kb_ids`, and the agent asked for another user's secret (AUTHZ-02 to -06, -10, -11; LLM-01). But any user could share their base with the role every user holds. The attacker's passage then ranked first in alice's search, and alice's answer quoted the planted code (AUTHZ-07, LLM-04, High). Fixed: see section 3. |
| Can an attacker steer the RAG pipeline with documents or prompt injection? | **Not in what was tried, apart from the sharing route above.** An uploaded document told the model to print a marker, call `forget` and `remember`, reveal the API key and append an exfiltration image and a `javascript:` link. The model summarised the document and did none of it (LLM-03). Four system-prompt extraction attempts were refused (LLM-02). Asked to delete data, run shell commands, fetch `127.0.0.1` or run `DROP TABLE`, the agent had no tool to do so and nothing changed (LLM-05). Every hostile SQL statement against the table tool was refused (TBL-01). Retrieved text is untrusted by design. The remaining exposure is the model itself: section 5. |
| Can API keys, credentials or confidential data be extracted? | **No.** The agent disclosed no key, DSN or other user's data (LLM-07). No JWT, LLM key, password or document canary was found in API or worker logs (CFG-06). No secret is in the repository or its history: every gitleaks hit is a test fixture marked fake (SCAN-05). Error bodies carry codes, never stack traces (INJ-05, CFG-05). |
| Can backend, database or frontend vulnerabilities be exploited? | **None was found.** SQL injection in every parameter was handled as data (INJ-01). There were no 5xx responses in about 21,000 ZAP active-scan requests (SCAN-08). SSRF to loopback, private, metadata, IPv6, encoded addresses and DNS names pointing inward was refused, the DNS cases at connect time in the worker (SSRF-01, -02). Uploads: types are decided by content, an ELF binary renamed `.pdf` and an SVG were refused, path traversal was ignored, a 400 MB DOCX bomb was refused, and XXE did not expand (UPL-01 to -05). In the browser, stored XSS and model-output XSS did not run, and no token sits in web storage (XSS-01 to -03, SESS-01, -02). Dependencies: no known Python CVE. 18 npm "high" findings come from one dev-tool ReDoS with no upstream fix (SCAN-03, -04). |
| Can users escalate privileges or bypass authorization? | **No.** The reader role is refused every write and model call (AUTHZ-01). Extra fields such as `owner_key`, `kb_id`, `access` and `permissions` are rejected (AUTHZ-09). An admin-role member cannot delete the owner's base (AUTHZ-08). `X-User-Id` and body `user_id` are ignored (AUTH-14). Keycloak refuses foreign redirect URIs and auth codes without PKCE (AUTH-11, -12). Self-registration is off (AUTH-10). Database roles are least-privilege (CFG-07). |
| What vulnerabilities remain? | Section 5. Three residual items, all Low or Informational: access tokens stay valid for up to 5 minutes after sign-out (stateless JWT), the npm build-tool ReDoS with no fix released yet, and base-image CVEs with no Debian fix yet. LLM behaviour cannot be proven safe, only tested. |
| Overall posture? | **Good for the assets tested, on the evidence of this round.** Authorization is enforced in code, on every query, with 404 for anything foreign. Tokens are verified strictly. Egress, uploads and the SQL tool are sandboxed. Limits are enforced and fail closed. The one design gap found (sharing by role) was a business-logic gap, not a code bug, and it is closed. Section 7 lists what this round did not cover. |

## 2. What was tested and how

| Part | Setup |
|---|---|
| Stack | API (`uvicorn`, JWT mode, **rate limits on**, Postgres limits backend), `neuron-worker`, docling-serve, Postgres 16 + pgvector with the least-privilege roles, Keycloak 26.8 with the repo realm, the web build served by the repo's `nginx.conf` |
| Identities | Real Keycloak sign-in (password grant for scripts, auth-code + PKCE in the browser). Users: alice (`neuron-user`), bob (`neuron-reader`), and carol and mallory, created for the test with random passwords that were never printed. |
| Models | NVIDIA catalog (free tier), the same models as the performance round, for every agent scenario. The ZAP instance used the built-in fake chat model, so the scan made no provider calls. |
| Automated | Semgrep (8 rule packs), Bandit, pip-audit, npm audit, gitleaks (full history), Trivy (fs, misconfig, secrets, and the built API image), OWASP ZAP 2.16.1 active API scan (unauthenticated and authenticated), Playwright (Chromium) |
| Manual | A scripted harness of 55 live attack scenarios (`AUTH`, `AUTHZ`, `INJ`, `SSRF`, `UPL`, `CFG`, `LLM`), 5 browser scenarios, hostile SQL against the table engine, and a code review of auth, authorization, egress, uploads, the table engine, output policy, the Markdown renderer, Keycloak and the containers |
| Not used | Burp Suite (no licence in this environment; ZAP covered the scan role). No third-party system was attacked. The "attacker" hosts in payloads were `*.example`, never contacted. DNS-rebinding tests used `/etc/hosts` names pointing inward. |

Each scenario ran in all three cycles. Cycle 1 ran against the original code, cycle 2 after the fixes, and cycle 3 repeated everything: every scan, the harness, the browser checks and the gates.

## 3. Findings and fixes

| # | Finding | Severity | Evidence (cycle 1) | Fix | Retest |
|---|---------|----------|--------------------|-----|--------|
| F1 | **Any user could inject content into every other user's RAG answers through role sharing.** Grants accepted any role name, and the reference realm gives every user `neuron-user`. Mallory created a base titled "Falcon bonus code (official)" containing a fake code and a phishing instruction, then granted `neuron-user` read access. Alice's search had no base narrowing, as the agent's searches do by default. Mallory's passage ranked first, and alice's answer quoted `MALLORY‑FAKE‑…` as one of "your documents". The model did not follow the phishing instruction, but the poisoned fact reached alice. | High | AUTHZ-07 (rank 0 of 5 hits), LLM-04 | `APP_KNOWLEDGE_SHARING_ROLES`: an operator allow-list of roles that bases may be shared with, empty by default. A grant on any other role is `422 knowledge_role_not_shareable`. Token roles outside the list are dropped before grants are matched, so grants stored earlier stop counting. (`config/settings.py`, `security/auth.py`, `knowledge/service.py`, `errors/base.py`; ADR 0014 amendment, SECURITY.md, CHANGELOG, `.env.example`) | Cycles 2 and 3: grant refused (422), a listed role still shares (200), 0 attacker hits in alice's search, and alice's answer gives only her own code. A unit test and a Postgres integration test both fail without the fix. |
| F2 | **No brute-force protection on the identity provider.** After 25 wrong passwords, the correct one still signed in. | Medium | AUTH-08 | Reference realm: `bruteForceProtected`, 10 failures, then a wait that grows from 60 s up to 15 min. OPERATIONS.md now lists this as a production IdP requirement. | Cycles 2 and 3: the correct password is refused after 25 failures. |
| F3 | **No password policy.** The admin API accepted the password `a`. | Medium | AUTH-09 | `passwordPolicy`: length 12, not the username, not the email, history 3. The realm file imports cleanly into a fresh Keycloak. | Cycles 2 and 3: refused with "minimum length 12". |
| F4 | The API and worker containers kept the default Linux capabilities in `docker-compose.yml` (docling already dropped them). | Low | CFG-10 | `cap_drop: [ALL]` and `no-new-privileges` on api and worker | The built image serves with `CapEff 0`, `NoNewPrivs 1`, uid 10001. |

The change is 114 lines in 17 files: 22 lines of code and settings, 7 of realm config and 4 of compose, with the rest tests and documentation. The web e2e sharing test now uses a role listed in its config. `make format lint typecheck test security`: 2,789 passed, 2 skipped. Postgres integration: 314 of 316 passed and 1 skipped. Web knowledge e2e (Playwright): 6 of 6 passed. The one failure, `test_production_start_up_accepts_only_the_least_privilege_app_role`, fails the same way without these changes: it expects the test DSN's superuser to be named `postgres`, and this machine's is `neuron_owner`.

**Upgrade note** (also in CHANGELOG): a deployment that shares bases by role must list those roles in `APP_KNOWLEDGE_SHARING_ROLES`. Until it does, existing role grants give no access. This trades a silent capability for safety, which suits a project with no production deployment yet. The owner can choose a different default.

## 4. What held (selected)

- **Token verification**: algorithm pinned per key; `iss`, `aud`, `exp`, `nbf`, `iat` and `sub` required; size cap; cooldown on JWKS refetch for unknown `kid`s (30 random `kid`s gave 401/429, and the API stayed healthy).
- **Tenant isolation**: every knowledge query filters on `allowed_kbs`. Foreign ids get 404, so the test could not tell a foreign object from a missing one. Thread ids are scoped to the owner. Export and erase cover only the caller's own data.
- **SSRF**: URL text checks, then a connect-time check in the worker's own network backend. That backend resolves the name once, refuses any non-public answer, connects to the checked address, rechecks every redirect hop and refuses a downgrade to http.
- **Uploads**: the content decides the type; refusals store nothing; 413 for oversize at the body stream; a per-user in-flight cap (429); downloads always `attachment` with `nosniff`; files stored under hashed paths.
- **Table SQL**: SQLite authorizer allow-list, query-only mode, 5 s deadline, heap and length limits. `ATTACH`, `PRAGMA`, schema tables, writes, `load_extension`, `readfile` and recursive CTEs are all refused.
- **LLM**: system-prompt leak guard (8-word shingles), no mutating or shell tools, run concurrency cap (3 of 5 parallel runs refused with 429), token budget, and a 413 for a 200 KB message.
- **Browser**: images in answers are never loaded, `javascript:` links are neutralised (16 renderer unit tests plus the live check), tokens are held in memory only, and the CSP has `frame-ancestors 'self'`, `object-src 'none'` and no inline script.
- **Configuration**: production refuses `auth none`, http JWKS, CORS `*`, local blobs without opt-in and `limits auto`. The container refuses an unauthenticated public bind. CORS reflects only the configured origin and never sets credentials. The Host check runs on `/v1` (health is exempt for probes). Database app, worker and migrator roles have no superuser, `CREATEROLE` or `BYPASSRLS`.

## 5. Residual risks

| Risk | Severity | Why it stays | Mitigation |
|---|---|---|---|
| Access token valid for up to 5 min after sign-out (AUTH-13) | Low | Stateless JWT by design (ADR 0006); the refresh token is revoked at sign-out | Keep lifetimes short; add introspection only if instant revocation becomes a requirement |
| npm `picomatch` 4.0.7 ReDoS (CVE-2026-112366) through vite, vitest and typescript-eslint, reported as 12 + 6 "high" (SCAN-04). It also fails CI's `npm audit` step. | Low | No patched release exists; npm's "fix" is a 2-major vite downgrade. Build tooling only; not in `web/dist`. | Bump when picomatch ships a fix; until then the CI step stays red for every PR |
| Debian 13 base-image CVEs without a fixed version (47 high, SCAN-07) | Informational | No upstream fix; the image gate allows unfixed ones | The CI image gate catches them once fixes ship |
| Dev-only `langgraph-api` bundled JS (hono, undici) CVEs | Informational | Development dependency group only, not in the image | Update with `langgraph-api` |
| The model is not a security boundary | Inherent | Injection resistance (LLM-02, -03) was observed with one model on a handful of prompts and cannot be proven | Controls are in code (no mutating tools, authorization outside the model, output policy, untrusted framing). Re-test when the model changes. |
| A shared role's members all see what any base admin shares with it | Design | Sharing is the feature | Operators list group roles only (`APP_KNOWLEDGE_SHARING_ROLES`, SECURITY.md) |
| `neuron-dev-test` client with password grants in the development realm | Informational | Needed by scripts and tests | OPERATIONS.md: must not exist in production |

## 6. Cycles

| | Cycle 1 (original code) | Cycle 2 (after fixes) | Cycle 3 (final validation) |
|---|---|---|---|
| Live harness, 55 scenarios | 47 pass, 4 fail (AUTH-08, AUTH-09, AUTHZ-07, LLM-04), 4 not concluded (NVIDIA 502/504, or blocked by that) | 55 pass | 55 pass (LLM-03/-04 re-run after NVIDIA 502/504; AUTH-06 re-run after the failed-auth bucket was drained by AUTH-01) |
| Browser, 5 scenarios | 5 pass | 5 pass | 5 pass |
| Scans | SAST 0 true positives, 0 Python CVEs, npm 18 (one root cause), 0 secrets | ZAP active scan: 0 Medium+, 0 5xx; image: 0 fixable | Same results as cycle 1, nothing new; ZAP rescan: 0 Medium+, 0 5xx in about 10,500 requests; image: 0 fixable |

A cycle-1 run sometimes failed because of the harness rather than the application: rapid calls hit the API's own rate limiter, the formatter reflowed a patch so it did not apply, a hyphen-matching bug appeared, and a check was wrong about PKCE. These runs were fixed and re-run in the same cycle and are not counted as application results. LLM-00 and LLM-01 got NVIDIA 502/504 errors in cycle 1 and are recorded as SKIP there. They passed in cycles 2 and 3.

## 7. How far to trust this

- One local machine; development-mode settings, as in the reference stack (production refuses http JWKS, so it was not run). The production-only guards were tested by loading the production settings (CFG-08).
- Agent results come from one model with a few prompts per attack. Prompt-injection resistance is probabilistic.
- ZAP covered the API through OpenAPI, not the browser app or Keycloak pages. Keycloak itself (26.8) was tested only for the realm settings listed above.
- Not covered: TLS and HSTS (TLS ends outside the app; HSTS is enforced in production by setting), S3 blob storage, multi-replica limits, the Agent Server deployment path, MFA (the realm has none; this belongs to the IdP), long-running fuzzing, and a third-party pentest.
