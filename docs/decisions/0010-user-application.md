# ADR 0010: User Application (v0.8.0)

## Status

Accepted (2026-10-28, owner approval). Inputs: `docs/releases/v0.8.0-research.md`. The owner answered the
research questions on 2026-10-28: Keycloak as the identity provider, a single-assistant
product shape (left to the architect), server-stored conversation titles, a Node toolchain
in the repository, feedback (#104) in this release, and the latest stable web stack with a
popular UI library. Production deployment stays out of scope until after v1.0.0 (owner
decision, 2026-10-27): every check in this release runs locally, on the fake model or the
NVIDIA development model.

**Amendments.**
- 2026-10-28: decision 7 now reads `frame-ancestors 'self'`, not `'none'`. Silent renew loads
  the app in a hidden frame of itself, so `'none'` blocks it; `'self'` still stops every
  other site from framing the app. If silent renew fails its real-browser test (open
  question 2), delete the renew frame and return to `'none'`.
- 2026-10-28: open question 3 is answered by ADR 0011. There is no thread-ownership table
  (ownership lives in checkpoint metadata), so titles get their own table and migration.

## Context

Through v0.7.0 neuron is an API: streaming, approvals, memory and data rights exist, but
nobody can use them without writing a client. The roadmap theme for v0.8.0 is "User
Application: Web UX + chat experience".

**Product requirement (chosen by the architect, confirmed by the owner's answers).** One
personal assistant per user, in a browser:

1. A signed-in user can chat, see the answer stream, stop a run and retry.
2. A user can list, resume, rename and delete their conversations.
3. When a run pauses for approval, the user sees the exact tool call from the server and
   approves or rejects it (the v0.7.0 memory flow, end to end).
4. A user can list and delete memories, export their data and erase it.
5. A user can rate an answer (thumbs up or down with a fixed reason), issue #104.

Not in scope: an agent picker, workspaces, shared or team conversations, admin screens,
file upload, voice, localisation, and any hosted deployment of the UI.

## Decisions

1. **Order of work.** (A) Backend gaps. (B) Local identity provider. (C) Web scaffold and
   stream client. (D) Screens. (E) UI security and the release gate. A and B are independent
   of each other; C needs B only for sign-in, not for its fake-server tests.

2. **Where it lives.** A separate single-page app in `web/`, in the same repository, served
   by its own origin and calling the API with CORS (`APP_CORS_ALLOWED_ORIGINS`, exact
   origin, bearer-only). The API image does not serve it and gains no static-file route.
   The API contract and the UI change in the same PR when they must.

3. **Stack.** React (current stable major), Vite, TypeScript in strict mode, Tailwind CSS
   with shadcn/ui components (copied source on Radix or Base UI primitives, so the
   dependency set stays small), TanStack Query for server state, Vitest and Testing
   Library for unit tests, Playwright for end-to-end tests. Versions are chosen at
   implementation from the npm registry and recorded in `web/package.json` and the
   lockfile; each new package must satisfy the 90-day rule of the `new-dependencies` job
   and `npm audit` must be clean (or the exception recorded). Package manager and Node
   version are pinned (`.nvmrc`, `packageManager`).

4. **Our own stream client.** A small `fetch` and `ReadableStream` reader for the
   existing seven-event contract (`STREAM_PROTOCOL_VERSION` 1), with `AbortController` for
   Stop. No chat framework and no protocol adapter (AG-UI, AI SDK, LangGraph SDK): the
   approval path is security-critical and the contract is small. Reconnect is not resume;
   a broken stream shows the partial answer and offers retry, and the history endpoint is
   the source of truth. `token` deltas are a preview and `final` replaces them.

5. **Sign-in.** Keycloak, run locally from `docker-compose` (a pinned image, `start-dev`,
   an imported realm `neuron`). The browser uses Authorization Code with PKCE (S256) with a
   public client; the access token lives in memory only, never in `localStorage` or
   `sessionStorage`; there is no cookie and no backend-for-frontend, so the bearer-only
   CORS design of ADR 0006 is unchanged. The realm is configuration, not code:
   - issuer `http://localhost:8080/realms/neuron`, JWKS from the realm's certs endpoint
     (HTTP is allowed only in development, as `Settings` already enforces);
   - an audience mapper so access tokens carry `aud=neuron-api`;
   - realm roles mapped to a top-level `roles` claim and `APP_AUTH_ROLE_PERMISSIONS`
     mapping them to the existing permissions (`agent:invoke`, `agent:approve`,
     `threads:*`, `memories:*`, plus `feedback:write`);
   - short access-token lifetimes; refresh only through Keycloak's own session (silent
     renew), no refresh token in script-readable storage.
   The API is provider-neutral: a hosted provider later is a settings change. The realm
   export is a development fixture with no real credentials and a test checks that.

6. **Backend gaps** (additive; `STREAM_PROTOCOL_VERSION` stays 1 for additive fields):
   - `run_id` on `run_started` and `final` (needed by feedback). Verified at implementation;
     it exists in graph state but may not reach the stream.
   - A bounded conversation title, owner-keyed, stored with the thread's other per-user
     state (the HMAC owner key, never the raw subject), set from the first user message
     truncated to 80 characters and editable by `PATCH /v1/threads/{id}`
     (`threads:write`). It is content, so it is covered by export, thread deletion and
     erasure, and it never appears in logs, spans or metrics. `GET /v1/me/threads` returns
     it. Storage is chosen in the title issue (a column in the existing thread-ownership
     table is preferred over the LangGraph store); a new migration follows ADR 0008's rules.
   - The messages replay includes tool-call and approval records (names and a bounded,
     server-rendered argument summary), so a resumed conversation matches what was seen.
   - `POST /v1/threads/{id}/runs/{run_id}/feedback` as written in #104: score -1 or 1, a
     fixed reason enum, no free text, scope `feedback:write`, owner check with the same 404
     for missing and foreign, idempotent per (owner, run), rate-limited, recorded as a log
     event, span event and metric by score and reason, never with content.

7. **Untrusted output.** Model text, tool output and titles are untrusted:
   - Markdown is rendered with a sanitising renderer; raw HTML is not rendered; links are
     `noopener noreferrer`, open in a new tab and show their target; images from model
     output are not loaded (an image URL is an exfiltration channel); code is text.
   - The approval card is a separate component rendered only from the server's
     `approval_required` payload, in a style the markdown renderer cannot produce; model
     text can never create or resolve one. Approve and reject act only on the id in that
     payload.
   - The host serves a strict CSP (no inline script, `connect-src` limited to the API and
     Keycloak origins, `frame-ancestors 'self'`, see Amendments). Titles are rendered as text.
   - A fixed UI security test set (XSS payloads in `token`, `final`, titles and tool
     summaries; markdown image beacons; look-alike approval text; open redirect in the
     sign-in callback) runs in CI.

8. **Accessibility and browsers.** WCAG 2.2 AA is the target for the chat and approval
   flows, checked with automated tests (axe) and a manual keyboard and screen-reader pass
   recorded in the release record. Last two versions of Chromium, Firefox and Safari
   engines; mobile layout works at 360 px wide.

9. **Verification.** Unit tests against a fake SSE server; Playwright end to end against
   `make api` with the fake model and the local Keycloak; one recorded run on the NVIDIA
   development model if a valid key exists, otherwise recorded as not run. No deployed
   environment is tested.

10. **Telemetry.** The browser sends no analytics and no third-party scripts. Client errors
    are shown, not reported. New server telemetry names (`user_feedback`, rename) are added
    to `semconv.py` and the Collector allow-list in the same PR, with the leak scan.

## Consequences

- A second language and toolchain enter CI (Node, npm audit, Playwright, a CSP check).
- The sign-in is verified against Keycloak only; another provider is a documented
  settings change, not a tested one.
- Titles are new stored content; the data-rights and leak tests must cover them.
- The UI makes prompt injection visible to users, so the UI security tests are a release
  gate, not an extra.

## Alternatives considered

- Serving the UI from the API image: one deploy, but a wider attack surface and coupled releases.
- Server-rendered pages (HTMX): no Node, but a poor fit for token streaming and approvals.
- A chat framework or protocol adapter (assistant-ui, AI SDK, AG-UI, LangGraph `useStream`):
  less code, but a translation layer or a different server protocol on the approval path
  and a larger dependency tree. Revisit if the hand-written message list becomes the largest cost.
- A backend-for-frontend with cookies: contradicts the bearer-only CORS design and needs
  CSRF controls.
- A hosted identity provider for development: needs an external account and key; Keycloak
  runs offline.

## Open questions

1. Keycloak image version and digest (chosen and pinned at implementation).
2. Silent renew without a script-readable refresh token depends on third-party cookie
   behaviour in browsers; if it proves unreliable on `localhost` across browsers, the
   fallback is a short re-login prompt, not storing a refresh token. To be proven in the
   sign-in issue.
3. Thread title storage (column versus store), decided in the title issue after reading the
   current ownership table.
4. Whether `PATCH /v1/threads/{id}` needs its own scope or reuses `threads:delete`'s
   sibling; proposed: a new `threads:write`.
