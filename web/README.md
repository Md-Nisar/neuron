# neuron web

The browser application for neuron (ADR 0010). React, Vite, strict TypeScript, Tailwind CSS and
shadcn/ui (copied source; add components with `npx shadcn@latest add <name>` and review the diff).

Needs Node from `.nvmrc` and the npm in `package.json` (`packageManager`). Run from the repo root:

    make web-install   # npm ci: installs from the lockfile only
    make web-dev       # http://127.0.0.1:5173 (the origin the dev Keycloak allows)
    make web           # format check, lint, typecheck, test, build, npm audit

Rules for this directory:

- Every dependency is an exact version; `.npmrc` turns install scripts off. A new package must be
  at least 90 days old on npm (the `new-dependencies` CI job), and `npm audit` must stay clean.
- Model, tool and title text is untrusted: no `dangerouslySetInnerHTML` (lint fails on it).
- The API image does not include this directory (`.dockerignore` is an allowlist).

## Stream client (`src/lib/stream`)

A small typed reader for `POST /v1/agent/stream` and the approval stream (no chat framework):

```ts
import { streamRun, reduceRunState, initialRunState, StreamStartError } from "@/lib/stream";

let state = initialRunState;
try {
  for await (const event of streamRun({ baseUrl, path: "/v1/agent/stream", token, body, signal })) {
    state = reduceRunState(state, event); // token deltas are a preview; `final` replaces them
  }
} catch (error) {
  if (error instanceof StreamStartError) {
    // before the first byte: kind is unauthorized, thread_busy, rate_limited (retryAfterSeconds), ...
  }
}
```

- Once streaming, the iteration always ends with `done`; a broken connection or malformed data
  yields a synthetic `error` first. Aborting `signal` ends it quietly.
- The token goes only in the `Authorization` header, only to `baseUrl`'s origin (a path that
  would change origin is refused), with no cookies and no redirects.
- `src/lib/stream/contract.json` is checked against the server's models by
  `tests/unit/test_web_stream_contract.py`; update both together when the protocol changes.

## Sign-in (`src/lib/auth`)

Authorization Code + PKCE (S256), written out in about 400 lines so each check is testable; no
OAuth library. Against the development Keycloak (`docker compose --profile keycloak up keycloak`,
`make dev-keycloak >> .env`, then `make web-dev`), sign in as `alice` / `dev-only-alice`.

Settings (build time, `web/.env.local`, both optional): `VITE_OIDC_ISSUER` (default
`http://localhost:8180/realms/neuron`; plain HTTP is accepted on loopback only) and
`VITE_OIDC_CLIENT_ID` (default `neuron-web`). The redirect URI is the page origin's root and
must equal the single URI the realm registers.

What it guarantees, each pinned by a test in `src/lib/auth/*.test.ts`:

- `state` and `nonce` are checked; the PKCE verifier never leaves the browser except in the
  token request; an `iss` that names another issuer is refused (RFC 9207).
- The provider's endpoints must be on the issuer's origin; the callback's `code` and `state` are
  removed from the address bar before anything else happens.
- After sign-in the user goes only to a local path (`//host`, `\host`, absolute and `javascript:`
  URLs fall back to `/`).
- The access token lives in a private field only: never in `localStorage`, `sessionStorage`,
  cookies, history, the URL or the console. The refresh token the provider returns is never read.
  `sessionStorage` holds just the one-time transaction across the redirect and it is deleted on
  the callback, whether or not it succeeds.
- Provider error text is never shown; the UI has fixed wording per reason.

**Silent renew is attempted but unproven in a real browser.** Before the token expires, a hidden
frame asks the provider's own session for a new one (`prompt=none`, no refresh token). Whether
that works on `localhost` across browsers depends on cookie behaviour (ADR 0010, open question 2).
It is tested here with a fake frame only. Any failure falls back to "Your session ended. Please
sign in again", never to storing a refresh token.

## Chat (`src/features/chat`)

Send, stream, stop, retry and new conversation over `POST /v1/agent/stream`, using the stream
client above. Settings (build time, both optional): `VITE_API_URL` (default `http://127.0.0.1:8000`;
`https` required except on loopback, an origin only) and `VITE_MAX_PROMPT_CHARS` (default 12000,
the server's `APP_MAX_PROMPT_CHARS`; the server stays authoritative).

- The composer mirrors the server's rules: trimmed, at most the limit in code points, no control
  characters except tab and line breaks. Enter sends, Shift+Enter adds a line.
- `token` events are a preview; `final` replaces it. A stopped or broken reply keeps its partial
  text, and Retry resends the same message without duplicating it (a failed run leaves no turn
  on the server, ADR 0005).
- Failures (401, 403, 404, 409 busy or approval pending, 429 with the wait, 5xx, no network, a
  broken stream) each have fixed wording; server and model text is never used for them. A 401
  also ends the local session.
- Assistant text is Markdown rendered as React elements: raw HTML stays literal text, images are
  never loaded, code is text, and only absolute `http(s)` and `mailto` links become links, each in
  a new tab with `noopener` and its real host shown next to the label.
- An `approval_required` reply shows the approval card (see below).

### Approval card

Rendered by `ApprovalCard`, only from the server's validated `approval_required` payload, outside
the Markdown renderer (which cannot produce a button or the card's double border).

- Approve and Reject call `POST /v1/threads/{id}/approvals/{approval_id}/stream` with the ids from
  that payload, validated again before they go into the URL path (an id of `.` or `..` is refused),
  and show the continuation as a new reply. Only the decisions the server offers appear.
- The tool name and arguments are shown in full, with control, zero-width and direction-override
  characters made visible (`[U+202E]`). If they are too long to show in full (4000 characters),
  Approve is disabled and only Reject is offered.
- One decision per approval, however many clicks (a synchronous guard, tested). If the approval
  is gone (`404`: decided in another tab, or expired) the card says so neutrally and does not
  claim a decision. `409`, `401`, a network failure or Stop leave it undecided and decidable.
- "You approved this" / "You rejected this" come from the user's click and the HTTP result, never
  from what the model says next.

## Your data (`src/features/data`)

The "Your data" page (opened from the nav; the chat stays mounted so a draft survives a visit) uses
the existing `/v1/me/*` routes and needs the scopes `memories:read`, `memories:write`,
`threads:read` and `threads:delete`.

- **Memories:** list (paged, shown as text), and delete in two steps. If memory is off on the
  server the page says so.
- **Export:** builds one dated JSON file in the page and hands it to the browser. The API pages
  threads and messages independently and refuses oversized pages, so the page sizes are halved on
  `413`. The file is checked for completeness (every thread has all its messages) and a partial file
  is never offered. Nothing is kept: the text lives in one click handler, the object URL is revoked
  right after the click, and no state, storage or cookie holds it (tested). Requests use
  `cache: "no-store"`. Past 64 MiB the export is refused.
- **Erase:** needs the typed phrase `erase my data`. The user is signed out only if the server
  reports the erase complete; if a conversation was busy and skipped, the page says how many
  and stays signed in so the user can repeat it.

**Dependency pins.** `package.json` holds `micromark` at 4.0.2 and `micromark-core-commonmark`
at 2.0.3 (`overrides`). Their next releases (2026-09-26) added a new package,
`micromark-util-edit-map`, first published 31 days before this was written, which fails the
90-day rule. Drop the overrides once that package is older than 90 days (after 2026-12-25) and
the gate (`scripts/check_new_npm_dependencies.py`) passes without them.
