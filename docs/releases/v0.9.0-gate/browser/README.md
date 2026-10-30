# Browser run (Chromium, local reference stack)

A Playwright run of the built web app against the reference stack and its Keycloak. It covers
most of the v0.8.0 browser gates (#293, #290) on this machine; the gates stay `deferred:post-1.0`
because nothing here ran on a hosted origin, in another browser, or against a provider on
another site.

Setup: `NEURON_IMAGE=neuron:ref make reference-up`, with `APP_CORS_ALLOWED_ORIGINS` set to
`["http://localhost:5173"]` on both replicas (the reference compose file leaves CORS off; this run
used an override file). Build the app with `VITE_API_URL=http://localhost:8101 npx vite build` in
`web/`, then serve `web/dist` on `127.0.0.1:5173` with the headers from `scripts/web_headers.py`
(`--development --api-origin http://localhost:8101 --issuer http://localhost:8180/realms/neuron
--format json > headers.json`, then `node serve.js headers.json`). The scripts need Playwright
(`require('playwright')`), which is not a repo dependency. Open the app as `localhost:5173`.

| File | What it does |
| --- | --- |
| `e2e-full.js` | 14 steps as `alice`: chat, feedback, approval, memories, resume, rename, XSS and beacon payloads, origins contacted, callback hygiene, unlisted redirect, CSP header, delete, export, erase. Result: `e2e-results.json` (14 pass) |
| `e2e-renew.js` | Inline script blocked by the CSP; 7 minutes idle past the 5-minute token lifetime, then chat. Result: `e2e-renew.json` (passes), `e2e-renew-before-fix.txt` (the session ended) |
| `e2e-clean.js` | Erases `alice`'s data between runs |

## Findings (all fixed on this branch unless noted)

1. **Rename never worked from a browser.** The API's CORS policy allowed `GET, POST, DELETE`; the
   web app renames with `PATCH`, so the preflight failed ("Could not reach the server"). Fixed in
   `api/main.py`, with a preflight test.
2. **Silent renew ended every session at token expiry.** The reference CSP had `frame-src` for the
   provider only; the frame is redirected back to the app, and `frame-src` is checked on each hop,
   so it ended on an error page. Fixed in `scripts/web_headers.py` (`'self'` added), with its test.
   After the fix the run stayed signed in and could chat after 7 minutes.
3. **Documented dev origin was wrong.** `make web-dev` was documented as `http://127.0.0.1:5173`;
   the realm registers only `http://localhost:5173/`, so sign-in from the documented URL fails with
   `Invalid parameter: redirect_uri`. Documentation corrected (`web/README.md`, `DEVELOPMENT.md`,
   `web/vite.config.ts`).
4. **Not a bug, but worth knowing:** a page reload signs the user out (the token is in memory only);
   one click on "Sign in" restores the session without a password prompt.
5. **Not fixed:** the reference compose file has no way to set `APP_CORS_ALLOWED_ORIGINS`, so the
   web app cannot reach the stack without an override file.

## Not covered

Chromium only; one machine; app and provider on the same site (`localhost`), so third-party cookie
blocking was not exercised; the model was the fake one, so streamed text is the word "token"; the
resume step checks the history opens after a reload, not a run interrupted mid-stream; no
Keycloak-side logout or `post.logout.redirect` check; no accessibility or visual checks.
