# ADR 0006: Authentication, Identity, and Authorization Model

## Status

Accepted.

## Problem

v0.3.0 protects conversation state with an owner value, but the caller chooses
that owner through `user_id` in the request body or `X-User-Id` on body-less
thread endpoints. This is an accidental-use guard, not authentication. Any
caller that learns a thread ID can attempt to claim its owner, and there is no
function-level authorization model for endpoints or tools.

v0.4.0 must establish a verified caller identity before model, tool, rate-limit,
or checkpoint work begins, then use that identity consistently for object and
function authorization. The design must work for both the self-hosted FastAPI
API and LangGraph Agent Server without introducing a user database or login UI.

## Requirements

- Verify OAuth 2.0/OIDC access tokens issued by an external identity provider.
- Authenticate human users and service accounts through the same bearer-token
  validation and authorization boundary; distinguish their permissions through
  scopes, not alternate identity headers or authentication mechanisms.
- Reject unauthenticated or invalid requests before agent, tool, or checkpoint work.
- Bind conversation ownership to a stable authenticated principal, not an email,
  username, request field, or header.
- Bind issuer into principal identity so equal `sub` values from different
  issuers cannot collide. A deployment trusts exactly one configured issuer in
  v0.4.0; multi-issuer routing is explicitly out of scope.
- Restrict endpoint and tool capabilities using explicit permissions.
- Fail closed when signing keys cannot be obtained and no valid cached key exists.
- Keep health endpoints public and retain an explicit, local-only development mode.
- Never log bearer tokens, claims, raw subjects, or issuer values.
- Keep deterministic tests and local development dependency-free.

## Options Considered

### Authentication mechanism

1. **Application API keys** — simple, but they do not provide a standard
   principal/issuer model, delegated authorization, or common key rotation semantics.
2. **Opaque bearer tokens with introspection (RFC 7662)** — centralizes validation,
   but adds a network dependency to every request and complicates outage handling.
3. **mTLS** — strong workload identity, but unsuitable as the only mechanism for
   user and service-account access across common HTTP clients.
4. **OIDC/OAuth 2.0 JWT access tokens with JWKS** — selected. The resource server
   validates signed tokens locally using cached public keys while the external IdP
   owns users, issuance, revocation policy, and key rotation.

### Principal identity

1. `sub` alone — rejected because subject values are only unique within an issuer.
2. Email or username — rejected because these values can change and are not
   guaranteed to be unique or immutable.
3. `(iss, sub)` — selected as the stable principal identity. A tenant claim is
   not part of the identity key in v0.4.0; multi-tenant semantics require a
   separate product requirement and ADR.

### Owner representation

1. Raw `(iss, sub)` — rejected because checkpoint state must not contain provider
   identity claims.
2. Unsalted `sha256(user_id)` — rejected because low-entropy identifiers can be
   dictionary-reversed and issuers cannot be distinguished safely.
3. Keyed HMAC-SHA256 — selected. The owner key is
   `HMAC-SHA256(APP_IDENTITY_HASH_KEY, iss + "\x1f" + sub)`, encoded as lowercase
   hexadecimal. The secret is available only through `Settings`.

### Authorization model

1. Authentication-only — rejected; knowing who called is not permission to invoke
   every operation.
2. Role names hard-coded into endpoints — rejected; roles are IdP-specific and
   make least-privilege policies difficult to test.
3. Explicit permission checks — selected. The application maps token scopes to a
   small, application-owned permission vocabulary and denies by default.

## Decision

### Authentication boundary

The API is an OAuth 2.0 resource server. Human callers and machine/service
accounts use the same bearer-token path; the IdP issues their tokens and scopes,
and Neuron applies the same validation and permission checks to both. There is
no service-account header bypass. Every `/v1/*` route receives a verified
`Principal` from a FastAPI dependency. `/health/live` and `/health/ready` remain
public; readiness reports an unavailable JWKS provider when JWT mode has no usable
cached key.

The initial principal contains only downstream policy inputs:

```text
Principal(
    issuer: str,
    subject: str,
    scopes: frozenset[str],
    token_id: str | None,
    expires_at: datetime,
)
```

The raw bearer token and unneeded claims do not enter graph state, checkpoints,
logs, or model input. The API layer uses issuer and subject only to derive the
owner key and authorization context.

JWT validation uses PyJWT and PyJWKClient with these rules:

- only configured asymmetric algorithms are accepted; the default allow-list is
  `RS256,ES256`;
- `none`, HMAC algorithms, and algorithm/key-type confusion are rejected;
- `iss`, `aud`, `exp`, `nbf`, `iat`, and `sub` are required and validated;
- issuer and audience are exact configured matches;
- clock leeway is configurable and bounded, defaulting to 30 seconds;
- `typ=at+jwt` validation is configurable and disabled by default for
  interoperability with existing providers;
- encoded tokens have a bounded size before parsing;
- JWKS keys are cached for a bounded TTL; an unknown `kid` triggers at most one
  bounded refresh for that request;
- JWKS retrieval uses HTTPS outside development and a bounded timeout;
- an IdP/JWKS outage with no usable cached key fails closed with `503`.

Missing or invalid credentials return `401` with stable `authentication_error`
and `WWW-Authenticate: Bearer error="invalid_token"`. Insufficient permissions
return `403` with the existing stable `authorization_error`. Validation reasons
may be logged as a small reason code (`expired`, `bad_signature`,
`wrong_audience`, and so on), but token and claim values are never logged.

### Configuration modes

`APP_AUTH_MODE` has two values:

| Mode | Allowed environments | Behavior |
| --- | --- | --- |
| `none` | development, test | Preserve v0.3.0 local behavior for deterministic tests; identity remains explicitly untrusted. |
| `jwt` | any; required in staging and production | Require a verified bearer token on every `/v1/*` route. |

JWT configuration is centralized in `Settings` and includes issuer, audience,
JWKS URL, algorithm allow-list, leeway, JWKS cache TTL, token-size limit, and
`APP_IDENTITY_HASH_KEY`. `none` is rejected by settings validation in staging
and production. Every new setting must appear in `.env.example`.

### Thread ownership

In JWT mode, the service derives ownership from the verified principal using the
keyed HMAC above. Body `user_id` and `X-User-Id` are ignored or rejected by the
API contract; they can never override the principal. Anonymous threads are not
created in JWT mode. The existing single `_owned_thread_state` path continues to
apply the same missing/foreign `404 thread_not_found` behavior to invoke, stream,
history, and delete.

The v0.3.0 SHA-256 owner values are not automatically accepted in JWT mode.
Automatic dual-hash reads would weaken the new boundary and make migration
ambiguous. Existing deployments must either run an explicit operator migration
to re-key known threads or allow them to expire under retention. The supported
v0.4.0 rollout is retention: before enabling JWT mode, operators must schedule
`make prune-threads` at least daily, retain the configured
`APP_THREAD_RETENTION_DAYS` window, and wait one full window after the last
legacy write before treating all legacy threads as expired. During the window,
legacy SHA-256 owners are intentionally inaccessible in JWT mode; do not enable
a dual-hash lookup. If access continuity is required, pause rollout and plan a
separately reviewed, authenticated re-key process rather than modifying hashes
in place without an owner-to-principal mapping. `none` mode
continues to support v0.3.0 behavior for local compatibility.

### Permissions

The initial application permission vocabulary is:

| Permission | Protected operation |
| --- | --- |
| `agent:invoke` | `/v1/agent/invoke` and `/v1/agent/stream` |
| `threads:read` | `GET /v1/threads/{thread_id}/messages` |
| `threads:delete` | `DELETE /v1/threads/{thread_id}` |

Permission checks happen outside the model loop and before service work. Tool
authorization remains code-enforced through the existing input-policy boundary;
v0.4.0 does not expose mutating tools. A tool is never authorized merely because
the model requested it.

### Rate limits, audit, and Agent Server

Per-principal quotas and concurrency limits are specified separately in issue
#56, but their identity source is this verified `Principal`, not an IP address
or request-provided user ID. Audit events from issue #57 use stable principal
metadata or a derived owner key and never raw claims.

The Agent Server/LangGraph Studio integration uses the same verifier and
principal rules through a custom auth handler. It must not create a second
authentication or ownership model; that integration is implemented in issue #58.

## Migration and rollout

1. Add explicit `AUTH_MODE=none` support and typed principal/policy interfaces
   while keeping local tests working.
2. Implement JWT verification and settings validation (#53).
3. Switch thread ownership to principal-derived HMAC (#54).
4. Enforce endpoint and tool permissions (#55).
5. Update Agent Server integration, limits, audit events, documentation, and
   security tests.
6. Before staging or production, set `AUTH_MODE=jwt`, configure the IdP/JWKS
   settings, provision `APP_IDENTITY_HASH_KEY`, and plan legacy-thread migration
   or the retention window.

## Non-goals

- Storing users, passwords, sessions, or refresh tokens in Neuron.
- Issuing tokens or implementing a login UI.
- Arbitrary issuer discovery or multi-tenant policy in one v0.4.0 deployment.
- Fine-grained thread sharing between principals.
- Mutating tools or human approval workflows; ADR 0003 still governs those.
- Distributed rate limiting or concurrency coordination; issue #56 retains that
  deployment decision.

## Consequences

Neuron depends on an external IdP and JWKS availability in JWT mode, but gains a
standard, testable trust boundary and can fail closed during key outages. Local
development remains simple through an explicit unauthenticated mode, while
staging and production cannot accidentally run without authentication.

The v0.3.0 request contract is breaking in authenticated deployments: callers
must send bearer tokens, and request-provided identity fields no longer control
ownership. Existing thread data requires an explicit migration or retention
plan. The design creates stable seams for per-principal limits, audit logging,
and Agent Server authentication without adding a user database.

## References

- [RFC 9700: OAuth 2.0 Security Best Current Practice](https://www.rfc-editor.org/rfc/rfc9700.html)
- [RFC 9068: JWT Profile for OAuth 2.0 Access Tokens](https://www.rfc-editor.org/rfc/rfc9068.html)
- [RFC 6750: OAuth 2.0 Bearer Token Usage](https://www.rfc-editor.org/rfc/rfc6750.html)
- [PyJWT JWKS usage](https://pyjwt.readthedocs.io/en/stable/usage.html#retrieve-rsa-signing-keys-from-a-jwks-endpoint)
- [LangGraph custom authentication](https://docs.langchain.com/langsmith/auth)
- GitHub issues [#52](https://github.com/Md-Nisar/neuron/issues/52), [#53](https://github.com/Md-Nisar/neuron/issues/53), [#54](https://github.com/Md-Nisar/neuron/issues/54), and [#55](https://github.com/Md-Nisar/neuron/issues/55)
