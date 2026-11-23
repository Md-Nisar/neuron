-- D3 hardening (ADR 0016 decision 5), adapted from nl2data-ref/sql/001_hardened_model_b.sql.
-- Run as a superuser in the D3 database, after 01_schema.sql.
--
-- Roles (cluster-wide, so prefixed d3_):
--   d3_analyst        data role: sales tables, rows of the claimed regions, no compensation
--   d3_manager        data role: as d3_analyst, plus sales.rep_compensation
--   d3_login_analyst  login; may only set claims and switch into d3_analyst
--   d3_login_manager  login; may only set claims and switch into d3_manager
-- One login per data role: even if a statement escaped validation, an analyst session holds
-- no path into the manager role.

-- 1. Nobody but app.set_claims may write settings (claims live in transaction-local GUCs).
REVOKE EXECUTE ON FUNCTION pg_catalog.set_config(text, text, boolean) FROM PUBLIC;

DO $$
DECLARE r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['d3_claims_owner', 'd3_analyst', 'd3_manager'] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('CREATE ROLE %I NOLOGIN', r);
    END IF;
  END LOOP;
  FOREACH r IN ARRAY ARRAY['d3_login_analyst', 'd3_login_manager'] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('CREATE ROLE %I LOGIN NOINHERIT', r);
    END IF;
  END LOOP;
END $$;

DROP SCHEMA IF EXISTS app CASCADE;
CREATE SCHEMA app;
GRANT EXECUTE ON FUNCTION pg_catalog.set_config(text, text, boolean) TO d3_claims_owner;
GRANT USAGE ON SCHEMA app TO d3_claims_owner;

-- 2. Claims: the user and the regions they may see. Transaction-local (third argument true).
CREATE FUNCTION app.set_claims(p_user text, p_regions text[])
RETURNS void LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog AS $$
  SELECT pg_catalog.set_config('app.user_id', p_user, true),
         pg_catalog.set_config('app.regions', array_to_string(p_regions, ','), true);
$$;
ALTER FUNCTION app.set_claims(text, text[]) OWNER TO d3_claims_owner;
REVOKE EXECUTE ON FUNCTION app.set_claims(text, text[]) FROM PUBLIC;

-- NULL when no claims are set, so every policy below fails closed.
CREATE FUNCTION app.regions() RETURNS text[] LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
  SELECT string_to_array(NULLIF(pg_catalog.current_setting('app.regions', true), ''), ',');
$$;
REVOKE EXECUTE ON FUNCTION app.regions() FROM PUBLIC;

-- 3. Logins: set claims, then switch into their one data role. Read-only and time-bounded.
GRANT USAGE ON SCHEMA app TO d3_login_analyst, d3_login_manager;
GRANT EXECUTE ON FUNCTION app.set_claims(text, text[]) TO d3_login_analyst, d3_login_manager;
GRANT d3_analyst TO d3_login_analyst;
GRANT d3_manager TO d3_login_manager;
ALTER ROLE d3_login_analyst SET default_transaction_read_only = on;
ALTER ROLE d3_login_manager SET default_transaction_read_only = on;
ALTER ROLE d3_login_analyst SET statement_timeout = '15s';
ALTER ROLE d3_login_manager SET statement_timeout = '15s';

-- 4. Data roles: SELECT on the sales schema only; compensation for managers only.
GRANT USAGE ON SCHEMA sales, app TO d3_analyst, d3_manager;
GRANT EXECUTE ON FUNCTION app.regions() TO d3_analyst, d3_manager;
GRANT SELECT ON sales.regions, sales.countries, sales.customers, sales.products,
  sales.sales_reps, sales.orders, sales.order_lines, sales.returns TO d3_analyst, d3_manager;
GRANT SELECT ON sales.rep_compensation TO d3_manager;

-- 5. Row-level security, forced even for the owner, on every table. Fail closed: no claims,
--    no rows. Reference tables need claims too; regional tables need a claimed region.
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['regions', 'countries', 'products'] LOOP
    EXECUTE format('ALTER TABLE sales.%I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE sales.%I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format('CREATE POLICY claims_required ON sales.%I FOR SELECT TO d3_analyst, d3_manager '
                   'USING (app.regions() IS NOT NULL)', t);
  END LOOP;
  FOREACH t IN ARRAY ARRAY['customers', 'sales_reps', 'orders', 'order_lines', 'returns',
                           'rep_compensation'] LOOP
    EXECUTE format('ALTER TABLE sales.%I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE sales.%I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format('CREATE POLICY region_scope ON sales.%I FOR SELECT TO d3_analyst, d3_manager '
                   'USING (region_id = ANY (app.regions()))', t);
  END LOOP;
END $$;
