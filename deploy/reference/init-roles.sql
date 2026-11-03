-- Reference stack only (ADR 0012 decision 3): the database roles of OPERATIONS.md,
-- "Database roles", with throwaway passwords. Runs once, as the bootstrap superuser, when the
-- data directory is first created. Never reuse these passwords anywhere else.
CREATE ROLE neuron_migrator LOGIN PASSWORD 'migrator-local-only'
    NOSUPERUSER NOCREATEDB NOCREATEROLE;
CREATE ROLE neuron_app LOGIN PASSWORD 'app-local-only'
    NOSUPERUSER NOCREATEDB NOCREATEROLE;
-- The ingestion worker (ADR 0014; RAG-02.01): `setup` grants it the knowledge rights it needs.
CREATE ROLE neuron_worker LOGIN PASSWORD 'worker-local-only'
    NOSUPERUSER NOCREATEDB NOCREATEROLE;
GRANT CONNECT ON DATABASE neuron TO neuron_migrator, neuron_app, neuron_worker;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
ALTER SCHEMA public OWNER TO neuron_migrator;
