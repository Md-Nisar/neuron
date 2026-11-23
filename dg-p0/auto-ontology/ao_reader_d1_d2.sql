-- DG-00.05: Auto Ontology's read-only logins on D1 and D2 (run as superuser on the spike cluster).
-- D1 and D2 have no row-level security and are not hardened (set_config stays executable), so
-- unlike d3_ao_reader (ao_reader.sql, D18) these need no grant beyond SELECT.
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'd1_ao_reader') THEN CREATE ROLE d1_ao_reader LOGIN; END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'd2_ao_reader') THEN CREATE ROLE d2_ao_reader LOGIN; END IF;
END $$;
ALTER ROLE d1_ao_reader SET default_transaction_read_only = on;
ALTER ROLE d1_ao_reader SET statement_timeout = '15s';
ALTER ROLE d2_ao_reader SET default_transaction_read_only = on;
ALTER ROLE d2_ao_reader SET statement_timeout = '15s';
\c d1
GRANT USAGE ON SCHEMA application, purchasing, sales, warehouse TO d1_ao_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA application, purchasing, sales, warehouse TO d1_ao_reader;
-- D2: each d2_<db> database grants SELECT to d2_ao_reader when it is loaded (../d2/load.sh).
