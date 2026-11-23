#!/usr/bin/env bash
# Load D1, Wide World Importers on Postgres, with one command (DG-00.02).
#   D1_SRC=/path/to/auto-ontology-eval D3_ADMIN_DSN="host=... port=... user=postgres" ./load.sh
# D1_SRC is a checkout of github.com/NVIDIA/auto-ontology-eval at e727e4d (MIT, data from
# Microsoft's sql-server-samples). Same steps as its scripts/seed/seed_wwi.py, but stops on the
# first error.
set -euo pipefail
: "${D1_SRC:?set D1_SRC to an auto-ontology-eval checkout at e727e4d}"
: "${D3_ADMIN_DSN:?set D3_ADMIN_DSN to a superuser connection string without dbname}"
[ "$(git -C "$D1_SRC" rev-parse HEAD)" = e727e4d6e1e198355099de4803590bb3681793a4 ] \
  || { echo "D1_SRC is not at e727e4d" >&2; exit 1; }
W="$D1_SRC/datasets/wideworldimporters"
DB="$D3_ADMIN_DSN dbname=d1"

psql "$D3_ADMIN_DSN dbname=postgres" -v ON_ERROR_STOP=1 -q \
  -c "DROP DATABASE IF EXISTS d1 WITH (FORCE)" -c "CREATE DATABASE d1"
for f in 01_schemas 02_sequences 03_tables 04_indexes; do
  psql "$DB" -v ON_ERROR_STOP=1 -q -f "$W/ddl/$f.sql"
done
for csv in "$W"/data/*.csv; do
  t=$(basename "$csv" .csv | tr '[:upper:]' '[:lower:]')
  psql "$DB" -v ON_ERROR_STOP=1 -q -c "\\copy $t FROM '$csv' WITH (FORMAT csv, HEADER true, NULL '\\N')"
done
for f in 05_fkeys 06_views; do
  psql "$DB" -v ON_ERROR_STOP=1 -q -f "$W/ddl/$f.sql"
done
echo "d1 loaded"
