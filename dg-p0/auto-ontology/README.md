# Auto Ontology on D3 (DG-00.04)

NVIDIA Auto Ontology 1.3.0 at `7dac5ff7bce3daf42e2115ef392146a542fa15d2`, run against the D3 mart
through its own read-only login. Decisions D17 and D18; findings F6 to F9 in the design spike log.

## What runs where

| Piece | How | Port (loopback) |
| --- | --- | --- |
| D3 mart | spike PostgreSQL 16 cluster (`d3/load.sh`), login `d3_ao_reader` | socket, 55432 |
| Metadata store | Docker `pgvector/pgvector:pg17` | 55433 |
| Backend | `python -m auto_ontology.server` from the pinned source | 3001 |
| Ingestion service | `python -m auto_ontology.ingestion_service` | 3002 |
| Gateway (Next.js, auth) | `next start` | 3000 |
| Egress logger | `egress_log.py` | 38999 |

The backend trusts an unauthenticated user header (F8): never expose 3001; call 3000 only.

Upstream's Compose builds two images. They were not built here, because the build would need
NVIDIA's Dockerfile edited to trust this sandbox's TLS-intercepting proxy. The same commands the
images run are used from the source checkout instead; where Docker builds work, upstream's
`docker-compose.yml` with this `env.sh` mapping is the equivalent.

## Steps

Prerequisites: Docker, `uv`, Node 22 with corepack, `psql`, the spike cluster with D3 loaded
(`d3/load.sh`), and `LLM_API_KEY`, `LLM_MODEL` in the environment (NVIDIA API catalog).

```sh
S=/some/scratch/dir; mkdir -p $S/ao
git clone https://github.com/NVIDIA/auto-ontology.git $S/auto-ontology
git -C $S/auto-ontology checkout --detach 7dac5ff7bce3daf42e2115ef392146a542fa15d2

# 1. Mart login (superuser, after d3/sql/05_hardening.sql)
psql "host=/var/lib/postgresql/dg-spike port=55432 dbname=d3 user=postgres" -f ao_reader.sql

# 2. Throwaway local secrets, outside the repository
umask 077
printf 'POSTGRES_PASSWORD=%s\nAUTO_ONTOLOGY_ADMIN_PASSWORD=%s\nAUTH_SECRET=%s\n' \
  "$(openssl rand -hex 16)" "$(openssl rand -hex 16)" "$(openssl rand -hex 32)" > $S/ao/local.env
export AO_LOCAL_ENV=$S/ao/local.env

# 3. Egress logger (UPSTREAM: an HTTPS proxy to chain to, if the host needs one)
UPSTREAM=127.0.0.1:38189 python3 egress_log.py 127.0.0.1:38999 $S/ao/egress.jsonl &

# 4. Metadata store
. $AO_LOCAL_ENV
docker run -d --name ao-meta -p 127.0.0.1:55433:5432 -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" -e POSTGRES_DB=auto_ontology pgvector/pgvector:pg17

# 5. Backend (uv cannot fetch the image's 3.12.16 here; 3.12.13 used)
cd $S/auto-ontology
UV_PROJECT_ENVIRONMENT=$S/aovenv UV_PYTHON=3.12.13 uv sync --no-dev --frozen
( . path/to/env.sh; $S/aovenv/bin/alembic upgrade head
  PORT=3001 $S/aovenv/bin/python -m auto_ontology.server &
  PORT=3002 $S/aovenv/bin/python -m auto_ontology.ingestion_service & )

# 6. Gateway
cd frontend
corepack pnpm@10.34.3 install --frozen-lockfile && corepack pnpm@10.34.3 build
( . path/to/env.sh; sh prisma/migrate.sh
  NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 NODE_USE_ENV_PROXY=1 \
    node_modules/.bin/next start -H 127.0.0.1 -p 3000 & )

# 7. Service account (viewer) and its API token; enables semantic compilation (A1)
AUTO_ONTOLOGY_ADMIN_EMAIL=admin@example.test python3 service_account.py http://127.0.0.1:3000

# 8. Wait for compilation, then one question end to end, then the write attempt
python3 ask.py http://127.0.0.1:3000 $S/ao/ask.jsonl "How many orders were placed in 2025?"
D3_DSN="host=/var/lib/postgresql/dg-spike port=55432" $S/aovenv/bin/python -I write_attempt.py \
  http://127.0.0.1:3000 $S/auto-ontology $S/ao/write.jsonl
```

## Files

| File | Purpose |
| --- | --- |
| `ao_reader.sql` | The mart login; includes the D18 `set_config` grant |
| `env.sh` | Maps `LLM_*` and the local secrets to Auto Ontology's settings; no secret in the file |
| `egress_log.py` | Logging CONNECT proxy: host and port of every outbound HTTPS connection |
| `service_account.py` | Viewer service account, API token, compilation switch |
| `ask.py` | One question through `/api/chat/completions` with the service token |
| `write_attempt.py` | Write requests through chat and the connector; table fingerprints before and after |
