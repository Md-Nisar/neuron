-- DG-00.04 (D17): Auto Ontology's own read-only login on the D3 mart.
-- Run as a superuser in database d3, after d3/sql/05_hardening.sql.
--
-- Auto Ontology connects with one connection string and cannot SET ROLE, so this login is its own
-- data role: current_user is d3_ao_reader, it is a member of no other role, and the A' policies
-- (keyed on current_user through app.role_regions) are extended to it.
-- Scope: all three regions; no confidential tables (rep_compensation, assessor_notes), matching
-- the D3 Ossie model. Read-only and time-bounded by default.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'd3_ao_reader') THEN
    CREATE ROLE d3_ao_reader LOGIN NOINHERIT;
  END IF;
END $$;
ALTER ROLE d3_ao_reader SET default_transaction_read_only = on;
ALTER ROLE d3_ao_reader SET statement_timeout = '15s';

INSERT INTO app.role_regions VALUES
  ('d3_ao_reader', 'EMEA'), ('d3_ao_reader', 'APAC'), ('d3_ao_reader', 'AMER')
ON CONFLICT DO NOTHING;

GRANT USAGE ON SCHEMA sales, skills, app TO d3_ao_reader;
GRANT SELECT ON app.role_regions TO d3_ao_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA sales, skills TO d3_ao_reader;
REVOKE SELECT ON sales.rep_compensation, skills.assessor_notes FROM d3_ao_reader;

-- Add the role to every existing policy.
DO $$
DECLARE
  p record;
BEGIN
  FOR p IN SELECT schemaname, tablename, policyname FROM pg_policies
           WHERE schemaname IN ('sales', 'skills', 'app') AND NOT ('d3_ao_reader' = ANY (roles))
  LOOP
    EXECUTE format('ALTER POLICY %I ON %I.%I TO d3_analyst_emea, d3_analyst_apac, d3_manager, d3_ao_reader',
                   p.policyname, p.schemaname, p.tablename);
  END LOOP;
END $$;
