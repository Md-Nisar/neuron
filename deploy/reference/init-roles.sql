-- Reference stack only (ADR 0012 decision 3): the two database roles of OPERATIONS.md,
-- "Database roles", with throwaway passwords. Runs once, as the bootstrap superuser, when the
-- data directory is first created. Never reuse these passwords anywhere else.
CREATE ROLE neuron_migrator LOGIN PASSWORD 'migrator-local-only'
    NOSUPERUSER NOCREATEDB NOCREATEROLE;
CREATE ROLE neuron_app LOGIN PASSWORD 'app-local-only'
    NOSUPERUSER NOCREATEDB NOCREATEROLE;
GRANT CONNECT ON DATABASE neuron TO neuron_migrator, neuron_app;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
ALTER SCHEMA public OWNER TO neuron_migrator;
