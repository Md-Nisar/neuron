# Pass 2: Security, Authorization and Data Exposure

Do source-to-sink taint analysis. First enumerate **sources** (untrusted inputs), then
**sinks** (privileged operations), then check every path between them for validation,
encoding, and authorization.

**Sources:** path/query params, headers (including `Host`, `X-Forwarded-*`), cookies, request
bodies, file uploads and filenames, webhook and queue payloads, data previously written by users
(stored XSS, second-order SQLi), third-party API responses, environment in multi-tenant runtimes,
and LLM output.

**Sinks:** DB queries, shell/process execution, file paths, outbound HTTP, HTML/template
rendering, redirects, deserializers, logs, auth decisions, money movement, and admin actions.

## 1. Authentication
- New routes, handlers, RPC methods, or consumers missing the auth middleware or decorator.
  Check route registration, not only the handler: is it under a public prefix or allowlist?
- JWT handling: signature not verified, `alg: none` or algorithm confusion accepted, `exp`/`aud`/
  `iss` not checked, keys hardcoded or shared across environments.
- Sessions: fixation (no rotation on login), no invalidation on logout or password change,
  cookies missing `Secure`/`HttpOnly`/`SameSite`.
- Password reset and magic-link tokens: predictable, long-lived, reusable, or leaked via `Referer`.
- CSRF on cookie-authenticated state-changing endpoints; CORS reflecting arbitrary origins with
  credentials allowed.

## 2. Authorization and Multi-Tenancy
- **IDOR/BOLA:** an object fetched by a client-supplied ID with no ownership or tenant predicate.
  Check reads, writes, deletes, and also list, search, export, bulk, and count endpoints.
- **Function-level authZ (BFLA):** admin or privileged operations reachable by regular roles;
  role checks only in the UI.
- **Mass assignment / over-posting:** binding request bodies directly onto entities, letting
  clients set `role`, `tenantId`, `isAdmin`, `price`, or `ownerId`.
- **Field-level exposure:** entities or serializers returning password hashes, tokens, internal
  flags, other users' PII, or soft-deleted data.
- Authorization decided by a check that is separate from the action and can go stale (TOCTOU),
  or done once at list time but not on the detail or action call.
- Background jobs, consumers, and internal endpoints that trust a `tenantId` or `userId` in the
  payload without verifying it.
- Hardcoded role checks that bypass the central policy engine (OPA/Rego, Casbin, Spring Security,
  Pundit), so policy changes do not apply here.
- **Verify:** write the exact request an attacker with a low-privilege account would send, and
  show what they get back.

## 3. Injection and Unsafe Execution
- **SQL/HQL/NoSQL:** string concatenation or interpolation into queries; dynamic `ORDER BY`,
  column, or table names without a strict allowlist; MongoDB operator injection (`{"$ne": null}`
  from JSON bodies); raw-query escape hatches in ORMs (`.raw()`, `text()`, `$queryRawUnsafe`).
- **Command:** `shell=True`, `exec`/`system` with interpolated input, argument injection
  (user input starting with `-`).
- **Template / SSTI:** user input used as a template, not as template data.
- **XSS:** `dangerouslySetInnerHTML`, `v-html`, `innerHTML`, `|safe`, `mark_safe`, `th:utext`,
  unescaped Markdown rendering, `javascript:` URLs in `href`.
- **Path traversal / Zip Slip:** user-controlled file paths or archive entries without
  canonicalization and a base-directory check.
- **Deserialization:** `pickle`, `yaml.load` (unsafe loader), Java `ObjectInputStream`, polymorphic
  JSON typing (Jackson default typing), PHP `unserialize` on untrusted data.
- **XXE:** XML parsers with external entities enabled.
- **SSRF:** outbound requests to user-influenced URLs without scheme/host allowlisting, including
  bypasses through redirects, DNS rebinding, IPv6 and decimal IP forms, and cloud metadata
  endpoints (`169.254.169.254`).
- **Open redirect:** `next`/`returnUrl` parameters redirecting to arbitrary hosts.
- **ReDoS:** catastrophic-backtracking regexes applied to user input.
- **Prototype pollution:** deep merge of user JSON into objects in JavaScript.
- **Header/log injection:** CRLF in headers; unescaped newlines in log lines enabling forged entries.
- **LLM/prompt injection:** untrusted content concatenated into prompts whose output triggers
  tools, queries, or privileged actions without validation.

## 4. Cryptography and Secrets
- Hardcoded secrets, keys, or credentials in code, config, tests, or Dockerfiles (report
  redacted).
- Password hashing with MD5/SHA-x or unsalted hashes, instead of argon2id, bcrypt, or scrypt.
- Tokens from non-cryptographic RNGs (`Math.random`, `java.util.Random`, `random`).
- ECB mode, static or reused IVs/nonces, home-made crypto, missing authentication (encryption
  without MAC/AEAD).
- Non-constant-time comparison of secrets, signatures, or tokens.
- TLS verification disabled (`verify=False`, `InsecureSkipVerify`, trust-all managers,
  `rejectUnauthorized: false`).

## 5. Sensitive Data Exposure
- Logging request bodies, auth headers, tokens, passwords, or PII; exceptions with sensitive
  context sent to error trackers.
- Stack traces, SQL errors, or internal hostnames returned to clients.
- PII or tokens in URLs (they end up in logs, history, and `Referer`).
- Sensitive responses cacheable by shared caches or CDNs (missing `Cache-Control: no-store`).
- Public buckets or long-lived pre-signed URLs instead of scoped, short-lived ones.
- Differing error messages or timings that allow account or resource enumeration.

## 6. Abuse and Denial of Service
- No rate limiting on login, OTP, password reset, signup, or expensive endpoints.
- Unbounded request body, upload size, page size (`?limit=1000000`), batch size, or query
  complexity (GraphQL depth).
- Decompression bombs; parsing huge JSON/XML into memory.
- File uploads trusting the client-supplied content type or extension, or stored where they can
  be executed or served from the main origin.

## Reporting Rules for This Pass
- Redact every secret or PII value; show the location and type only.
- Include a concrete attack request or payload *shape* that demonstrates reachability; do not
  write weaponized exploit chains.
- Rate exploitability honestly: unauthenticated and internet-facing outranks authenticated
  admin-only.

## Common False Positives in This Pass
- ORM query builders and parameterized queries flagged as SQL injection.
- Template engines that auto-escape by default (React JSX, Jinja2 with autoescape, Thymeleaf
  `th:text`) flagged as XSS.
- Auth enforced by global middleware or a gateway: confirm the route is actually covered before
  dismissing, and before reporting.
- Tenant isolation enforced by row-level security or a global query filter (Hibernate
  `@Filter`, Django default managers, Postgres RLS); verify it is enabled on this path.
