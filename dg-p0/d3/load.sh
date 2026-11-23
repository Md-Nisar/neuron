#!/usr/bin/env bash
# Load the D3 mart with one command (DG-00.01).
#   D3_ADMIN_DSN="host=... port=... user=postgres" ./load.sh
# Creates (or recreates) database d3, then applies schema, hardening and seed.
set -euo pipefail
cd "$(dirname "$0")"
: "${D3_ADMIN_DSN:?set D3_ADMIN_DSN to a superuser connection string without dbname}"

psql "$D3_ADMIN_DSN dbname=postgres" -v ON_ERROR_STOP=1 -q \
  -c "DROP DATABASE IF EXISTS d3 WITH (FORCE)" -c "CREATE DATABASE d3"
for f in sql/01_schema.sql sql/02_hardening.sql sql/03_seed.sql; do
  psql "$D3_ADMIN_DSN dbname=d3" -v ON_ERROR_STOP=1 -q -f "$f"
done
echo "d3 loaded"
