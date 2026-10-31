# Local stack: API in Docker plus the web app

Development only. The API, Postgres and Keycloak run in Docker (`docker-compose.yml`, `keycloak`
profile), and the web app runs on the Vite dev server. Every port binds to loopback.

## 1. Steps to start

Prerequisites: Docker, `uv sync`, `make web-install`, and a `.env` (`cp .env.example .env`). A
model key in `.env` (for example `NVIDIA_API_KEY` with `APP_DEFAULT_MODEL`) is optional; without
one, development falls back to the fake model.

1. Create `.dev/web.override.yml` (`.dev/` is git-ignored). Values set here replace the
   auth and CORS settings in `.env` for the API container only, so `.env` stays unchanged. The JWKS
   URL is the in-network Keycloak address; the issuer stays the browser-visible `localhost:8180`.

   ```yaml
   services:
     api:
       environment:
         APP_AUTH_MODE: jwt
         APP_AUTH_ISSUER: http://localhost:8180/realms/neuron
         APP_AUTH_AUDIENCE: neuron-api
         APP_AUTH_JWKS_URL: http://keycloak:8080/realms/neuron/protocol/openid-connect/certs
         APP_AUTH_ALGORITHMS: '["RS256"]'
         APP_AUTH_ROLE_PERMISSIONS: '{"neuron-user":["agent:approve","agent:invoke","feedback:write","memories:read","memories:write","threads:delete","threads:read","threads:write","tools:calculator","tools:forget","tools:recall","tools:remember"],"neuron-reader":["threads:read"]}'
         APP_IDENTITY_HASH_KEY: dev-web-identity-key-local-only-000000001
         APP_CORS_ALLOWED_ORIGINS: '["http://localhost:5173"]'
   ```

2. Build the Neuron login theme (Keycloakify, `keycloak-theme/`; needs Node 22, Maven and a JDK).
   Keycloak loads `keycloak-theme/dist_keycloak/neuron-theme.jar` from its `providers/` mount, and
   the realm selects it (`"loginTheme": "neuron"`). Rebuild after changing the theme, then
   recreate the `keycloak` container.

   ```bash
   npm --prefix keycloak-theme ci
   npm --prefix keycloak-theme run build-keycloak-theme
   ```

3. Start the API, Postgres and Keycloak:

   ```bash
   docker compose -f docker-compose.yml -f .dev/web.override.yml --profile keycloak up -d --build
   ```

4. Start the web app (in a second terminal):

   ```bash
   make web-dev
   ```

5. Open <http://localhost:5173> (not `127.0.0.1`: the development realm allows only the
   `localhost` origin) and sign in as `alice` / `dev-only-alice` (`bob` / `dev-only-bob` has the
   read-only `neuron-reader` role).

6. Check it is up: `curl http://127.0.0.1:8000/health/ready` returns `"status":"ready"`, and
   `POST /v1/agent/stream` without a token returns 401.

To stop: end `make web-dev`, then

```bash
docker compose -f docker-compose.yml -f .dev/web.override.yml --profile keycloak down
```

Add `-v` to also delete the Postgres volume (all local threads). The volume stores a check value
for `APP_IDENTITY_HASH_KEY`, so changing that key (for example, switching between `.env` and the
override) needs `down -v` first, or `setup` refuses the new key (`SECURITY.md`).

## 2. Services

| Service | URL | Notes |
|---|---|---|
| Web (Vite dev server) | <http://localhost:5173> | Sign in as `alice` / `dev-only-alice` |
| API (Docker) | <http://127.0.0.1:8000> | Ready check: `/health/ready` |
| Keycloak (Docker) | <http://localhost:8180> | Admin console: `admin` / `admin-local-only` |
| Postgres (Docker) | compose network only | No host port; reached by the API as `postgres:5432` |

All credentials above are throwaway development values from `docker-compose.yml` and
`deploy/keycloak/neuron-realm.json`.
