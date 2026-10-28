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
