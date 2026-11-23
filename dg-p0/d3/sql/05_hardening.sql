-- D3 hardening, option A' (owner decision D5; findings F1, F1b, F1c in the design spike log).
-- Run as a superuser in the D3 database, after both schemas and seeds.
--
-- Access is keyed on the data role, never on a session setting:
--   * every policy compares region_id with the regions mapped to `current_user` in
--     app.role_regions, which only the superuser can write;
--   * each data role has its own login, and each login is a member of exactly one data role, so
--     neither SET, RESET ROLE nor SET ROLE can widen what a session sees.
--
-- Data role          Login                   Regions            Confidential tables
-- d3_analyst_emea    d3_login_analyst_emea   EMEA               none
-- d3_analyst_apac    d3_login_analyst_apac   APAC               none
-- d3_manager         d3_login_manager        EMEA, APAC, AMER   rep_compensation, assessor_notes
--
-- Residual (F1c): a role's statement_timeout is a default the session can lift with a second
-- statement. PostgreSQL 16 cannot prevent that; the executor sets SET LOCAL statement_timeout
-- itself and runs exactly one validated SELECT.

-- 1. ADR 0016 decision 5: nobody may write settings through set_config. Authorization no longer
--    depends on settings, so this is defence in depth only.
REVOKE EXECUTE ON FUNCTION pg_catalog.set_config(text, text, boolean) FROM PUBLIC;

DO $$
DECLARE
  r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['d3_analyst_emea', 'd3_analyst_apac', 'd3_manager'] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('CREATE ROLE %I NOLOGIN', r);
    END IF;
  END LOOP;
  FOREACH r IN ARRAY ARRAY['d3_login_analyst_emea', 'd3_login_analyst_apac', 'd3_login_manager'] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('CREATE ROLE %I LOGIN NOINHERIT', r);
    END IF;
  END LOOP;
END $$;

-- 2. Role-to-region mapping: written by the superuser only, readable by the data roles.
DROP SCHEMA IF EXISTS app CASCADE;
CREATE SCHEMA app;
CREATE TABLE app.role_regions (
  role_name name NOT NULL,
  region_id text NOT NULL REFERENCES sales.regions,
  PRIMARY KEY (role_name, region_id)
);
INSERT INTO app.role_regions VALUES
  ('d3_analyst_emea', 'EMEA'), ('d3_analyst_apac', 'APAC'),
  ('d3_manager', 'EMEA'), ('d3_manager', 'APAC'), ('d3_manager', 'AMER');

-- 3. Logins: one data role each; read-only and time-bounded by default.
GRANT d3_analyst_emea TO d3_login_analyst_emea;
GRANT d3_analyst_apac TO d3_login_analyst_apac;
GRANT d3_manager TO d3_login_manager;
DO $$
DECLARE
  r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['d3_login_analyst_emea', 'd3_login_analyst_apac', 'd3_login_manager'] LOOP
    EXECUTE format('ALTER ROLE %I SET default_transaction_read_only = on', r);
    EXECUTE format('ALTER ROLE %I SET statement_timeout = %L', r, '15s');
  END LOOP;
END $$;

-- 4. Data roles: SELECT only. Confidential tables for the manager only.
GRANT USAGE ON SCHEMA sales, skills, app TO d3_analyst_emea, d3_analyst_apac, d3_manager;
GRANT SELECT ON app.role_regions TO d3_analyst_emea, d3_analyst_apac, d3_manager;
GRANT SELECT ON ALL TABLES IN SCHEMA sales, skills TO d3_analyst_emea, d3_analyst_apac, d3_manager;
REVOKE SELECT ON sales.rep_compensation, skills.assessor_notes FROM d3_analyst_emea, d3_analyst_apac;

-- 5. Row-level security, forced, on every table in both schemas. A role with no mapping sees no
--    rows, including reference tables.
DO $$
DECLARE
  t record;
  mapped constant text := 'region_id IN (SELECT m.region_id FROM app.role_regions m '
                          'WHERE m.role_name = current_user)';
  any_mapping constant text := 'EXISTS (SELECT 1 FROM app.role_regions m '
                               'WHERE m.role_name = current_user)';
BEGIN
  FOR t IN
    SELECT c.table_schema, c.table_name,
           bool_or(c.column_name = 'region_id') AS regional
    FROM information_schema.columns c
    JOIN information_schema.tables tb USING (table_schema, table_name)
    WHERE c.table_schema IN ('sales', 'skills') AND tb.table_type = 'BASE TABLE'
    GROUP BY c.table_schema, c.table_name
  LOOP
    EXECUTE format('ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY', t.table_schema, t.table_name);
    EXECUTE format('ALTER TABLE %I.%I FORCE ROW LEVEL SECURITY', t.table_schema, t.table_name);
    -- sales.regions and sales.countries carry region_id but are reference data: everyone mapped
    -- sees all of them.
    EXECUTE format('CREATE POLICY scope ON %I.%I FOR SELECT TO d3_analyst_emea, d3_analyst_apac, '
                   'd3_manager USING (%s)', t.table_schema, t.table_name,
                   CASE WHEN t.regional AND (t.table_schema, t.table_name) NOT IN
                          (('sales', 'regions'), ('sales', 'countries'))
                        THEN mapped ELSE any_mapping END);
  END LOOP;
END $$;

-- 6. Finding F3: the mapping itself is row-filtered, so a data role sees only its own regions.
--    The policies above read it as the invoking role, which needs exactly those rows.
ALTER TABLE app.role_regions ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.role_regions FORCE ROW LEVEL SECURITY;
CREATE POLICY own_mapping ON app.role_regions FOR SELECT TO d3_analyst_emea, d3_analyst_apac, d3_manager
  USING (role_name = current_user);
