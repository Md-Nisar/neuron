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
