# Local stack: everything in Docker

Development only. `docker-compose.yml` runs the whole stack, and every port binds to loopback.
You need Docker with Compose v2; Python, Node, Maven and a JDK are not needed on the host.

## 1. Start and stop

```bash
docker compose up --build        # or `make up` (detached, waits until healthy)
```

The first build takes a few minutes. Then open <http://localhost:5173>. Use `localhost`, not
`127.0.0.1`: the development realm allows only that origin. Sign in as `alice` /
`dev-only-alice`; `bob` / `dev-only-bob` has the read-only `neuron-reader` role.

Check it is up: `curl http://127.0.0.1:8000/health/ready` returns `"status":"ready"`, and
`POST /v1/agent/stream` without a token returns 401.

To stop, run `docker compose down` (or `make down`). Add `-v` to also delete the data: threads,
knowledge bases and uploaded files. The database stores a check value for
`APP_IDENTITY_HASH_KEY`, so changing that key needs `down -v` first, or `setup` refuses the new
key (`SECURITY.md`).

## 2. Services

| Service | URL | Notes |
|---|---|---|
| `web` | <http://localhost:5173> | The built app, served by unprivileged nginx |
| `api` | <http://127.0.0.1:8000> | JWT from the local Keycloak; knowledge on |
| `keycloak` | <http://localhost:8180> | Realm `neuron` with the login theme built into the image; admin console `admin` / `admin-local-only` |
| `worker` | none | Parses and embeds uploads; holds only its own database role |
| `postgres` | compose network only | pgvector, with the roles of `OPERATIONS.md`, "Database roles" |
| `setup` | none | Migrations and grants; runs once and exits |
| `docling` | none | Only with the `pdf` profile: on an internal network with no route out, read-only |

The credentials are throwaway development values from `docker-compose.yml`,
`deploy/reference/init-roles.sql` and `deploy/keycloak/neuron-realm.json`.

## 3. Options in `.env`

Compose reads `.env` next to `docker-compose.yml`. Every setting is optional.

| Set | Effect |
|---|---|
| `NVIDIA_API_KEY` (or `OPENAI_API_KEY`) and `APP_DEFAULT_MODEL` | A real model instead of the fake development model, for example `APP_DEFAULT_MODEL=nvidia:nvidia/nemotron-3-ultra-550b-a55b` |
| `APP_KNOWLEDGE_EMBEDDING_PROVIDER=nvidia` | Real embeddings (needs `NVIDIA_API_KEY`); document text is sent to NVIDIA's API. Changing the provider needs `down -v`, because vectors from different providers do not mix. |
| `COMPOSE_PROFILES=pdf` and `APP_KNOWLEDGE_PARSER_URL=http://docling:5001` | PDF and Office parsing through docling-serve. The image is 7.6 GB and takes about 2.5 minutes to start. Without it, those files fail at once with "Document processing is not set up on this service". |

## 4. Working on the web app

To get hot reload, run the rest of the stack in Docker and the Vite dev server on the host. The
dev server uses the same port and origin.

```bash
docker compose up --build -d
docker compose stop web
make web-dev
```

After changing the login theme in `keycloak-theme/`, run `docker compose up --build keycloak`.
