#!/usr/bin/env bash
# D2 (DG-00.05): BIRD Mini-Dev, PostgreSQL edition, one database per BIRD database (d2_<db_id>),
# plus the read-only logins d2_reader (scoring) and d2_ao_reader (Auto Ontology).
#   BIRD_SRC=/path/to/minidev ./load.sh   (minidev.zip from bird-bench.oss-cn-beijing.aliyuncs.com,
#   sha256 cc48ba16838204e4e214512030cb572eeb5f7bcdd999bae4b9b6ff12ec13b92f, unzipped)
# The dump holds all 75 tables in one public schema; it is loaded once into d2_all, each BIRD
# database's tables (dev_tables.json) are copied into their own database, and d2_all is dropped.
set -euo pipefail
: "${BIRD_SRC:?}"
H="-h ${PGHOST:-/var/lib/postgresql/dg-spike} -p ${PGPORT:-55432} -U postgres"
psql -X -q $H -d postgres -v ON_ERROR_STOP=1 <<'SQL'
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'd2_reader') THEN CREATE ROLE d2_reader LOGIN; END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'd2_ao_reader') THEN CREATE ROLE d2_ao_reader LOGIN; END IF;
END $$;
ALTER ROLE d2_reader SET default_transaction_read_only = on;
ALTER ROLE d2_reader SET statement_timeout = '15s';
ALTER ROLE d2_ao_reader SET default_transaction_read_only = on;
ALTER ROLE d2_ao_reader SET statement_timeout = '15s';
CREATE DATABASE d2_all;
SQL
sed '/OWNER TO xiaolongli/d' "$BIRD_SRC/MINIDEV_postgresql/BIRD_dev.sql" | psql -X -q $H -d d2_all > /dev/null
python3 -c "
import json, sys
for d in json.load(open(sys.argv[1])): print(d['db_id'], ' '.join(t.lower() for t in d['table_names_original']))
" "$BIRD_SRC/MINIDEV/dev_tables.json" | while read -r db tables; do
  args=()
  for t in $tables; do args+=(-t "public.\"$t\""); done
  psql -X -q $H -d postgres -c "CREATE DATABASE d2_$db"
  pg_dump $H -d d2_all --no-owner --no-privileges "${args[@]}" | psql -X -q $H -d "d2_$db" -v ON_ERROR_STOP=1 > /dev/null
  psql -X -q $H -d "d2_$db" -c "REVOKE CREATE ON SCHEMA public FROM PUBLIC;
    GRANT USAGE ON SCHEMA public TO d2_reader, d2_ao_reader;
    GRANT SELECT ON ALL TABLES IN SCHEMA public TO d2_reader, d2_ao_reader; ANALYZE;"
done
psql -X -q $H -d postgres -c "DROP DATABASE d2_all"
