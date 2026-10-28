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
