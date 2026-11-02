#!/usr/bin/env bash
# Run the Postgres tests locally against a throwaway container (#374).
#
# Uses the same pinned image, pytest selection and skip check as the postgres-integration CI job,
# without TLS. An APP_TEST_POSTGRES_DSN already in the environment is used as is, with no
# container. The container listens on a random loopback port and is removed on exit.
set -euo pipefail
cd "$(dirname "$0")/.."

junit="$(mktemp)"
cleanup() { rm -f "$junit"; [ -n "${cid:-}" ] && docker rm -f "$cid" >/dev/null; return 0; }
trap cleanup EXIT

if [ -z "${APP_TEST_POSTGRES_DSN:-}" ]; then
  image="$(sed -n 's/^ *POSTGRES_IMAGE: *//p' .github/workflows/postgres-integration.yml)"
  password="local-only-throwaway"
  cid="$(docker run -d -p 127.0.0.1::5432 -e POSTGRES_PASSWORD="$password" "$image")"
  # TCP, not the socket: the image's temporary initialisation server listens on the socket only.
  for _ in $(seq 30); do
    docker exec "$cid" pg_isready -h 127.0.0.1 -U postgres >/dev/null 2>&1 && break
    sleep 2
  done
  docker exec "$cid" pg_isready -h 127.0.0.1 -U postgres >/dev/null
  port="$(docker port "$cid" 5432/tcp | head -n1 | sed 's/.*://')"
  export APP_TEST_POSTGRES_DSN="postgresql://postgres:${password}@127.0.0.1:${port}/postgres"
fi

uv run python -m pytest -m postgres -rs --junitxml="$junit" "$@"
uv run python scripts/require_postgres_tests.py "$junit"
