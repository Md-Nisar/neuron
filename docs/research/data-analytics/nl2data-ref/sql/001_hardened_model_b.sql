-- Hardened identity model B for Postgres 16: per-domain read-only roles, RLS keyed on
-- claims that ONLY a SECURITY DEFINER function can set, set_config revoked from PUBLIC.
-- Run as a superuser/owner. Idempotent enough for test setup.

CREATE SCHEMA IF NOT EXISTS certified;
CREATE SCHEMA IF NOT EXISTS app;

CREATE TABLE IF NOT EXISTS certified.fct_revenue (
  region text NOT NULL, fiscal_quarter text NOT NULL, net_revenue numeric NOT NULL);
TRUNCATE certified.fct_revenue;
INSERT INTO certified.fct_revenue VALUES
  ('APAC','FY26-Q2',100),('APAC','FY26-Q3',90),('EMEA','FY26-Q2',200),('EMEA','FY26-Q3',210);

-- 1. Claims live in transaction-local GUCs, but nobody except app.set_claims may write them.
REVOKE EXECUTE ON FUNCTION pg_catalog.set_config(text, text, boolean) FROM PUBLIC;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_claims_owner') THEN
    CREATE ROLE app_claims_owner NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_ro_finance') THEN
    CREATE ROLE agent_ro_finance NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_login_finance') THEN
    CREATE ROLE agent_login_finance LOGIN NOINHERIT; END IF;
END $$;
GRANT EXECUTE ON FUNCTION pg_catalog.set_config(text, text, boolean) TO app_claims_owner;
GRANT USAGE ON SCHEMA app TO app_claims_owner;

CREATE OR REPLACE FUNCTION app.set_claims(p_user text, p_regions text[])
RETURNS void LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog AS $$
  SELECT pg_catalog.set_config('app.user_id', p_user, true),
         pg_catalog.set_config('app.regions', array_to_string(p_regions, ','), true);
$$;
ALTER FUNCTION app.set_claims(text, text[]) OWNER TO app_claims_owner;
REVOKE EXECUTE ON FUNCTION app.set_claims(text, text[]) FROM PUBLIC;

CREATE OR REPLACE FUNCTION app.regions() RETURNS text[] LANGUAGE sql STABLE AS $$
  SELECT string_to_array(NULLIF(pg_catalog.current_setting('app.regions', true), ''), ',');
$$;

-- 2. One login per domain (no cross-domain membership); it may only set claims and switch
--    into its single data role. Settings live on the LOGIN role (applied at connect).
GRANT USAGE ON SCHEMA app TO agent_login_finance;
GRANT EXECUTE ON FUNCTION app.set_claims(text, text[]) TO agent_login_finance;
GRANT agent_ro_finance TO agent_login_finance;
ALTER ROLE agent_login_finance SET default_transaction_read_only = on;
ALTER ROLE agent_login_finance SET statement_timeout = '15s';

-- 3. Data role: SELECT on curated schema only; no app.set_claims, no set_config.
GRANT USAGE ON SCHEMA certified, app TO agent_ro_finance;
GRANT EXECUTE ON FUNCTION app.regions() TO agent_ro_finance;
GRANT SELECT ON certified.fct_revenue TO agent_ro_finance;

-- 4. RLS, forced even for the owner; fail closed when claims are missing (NULL -> no rows).
ALTER TABLE certified.fct_revenue ENABLE ROW LEVEL SECURITY;
ALTER TABLE certified.fct_revenue FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS region_scope ON certified.fct_revenue;
CREATE POLICY region_scope ON certified.fct_revenue FOR SELECT TO agent_ro_finance
  USING (region = ANY (app.regions()));
