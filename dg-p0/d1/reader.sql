-- D1 read-only login (DG-00.03). D1 has no row-level security: one reader sees all of it.
-- No access to the website views or history tables is needed, but they are read-only anyway.
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'd1_reader') THEN
    CREATE ROLE d1_reader LOGIN;
  END IF;
END $$;
ALTER ROLE d1_reader SET default_transaction_read_only = on;
GRANT CONNECT ON DATABASE d1 TO d1_reader;
GRANT USAGE ON SCHEMA application, purchasing, sales, warehouse TO d1_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA application, purchasing, sales, warehouse TO d1_reader;
