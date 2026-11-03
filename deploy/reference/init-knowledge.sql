-- Reference stack only (ADR 0014, RAG-01.01): what the operator runs once as a superuser before
-- `setup` with APP_KNOWLEDGE_ENABLED=true (OPERATIONS.md, "Database roles"). pgvector is not a
-- trusted extension and the migrator has no CREATE on the database, so neither can be left to
-- `setup`. Harmless while knowledge is off: nothing reads the schema.
-- The extension's types and operators go in `public` (migrator-owned, no PUBLIC CREATE) and are
-- usable by every role, which is expected. `setup` refuses a schema anyone else can create in.
CREATE EXTENSION IF NOT EXISTS vector SCHEMA public;
CREATE SCHEMA IF NOT EXISTS knowledge AUTHORIZATION neuron_migrator;
REVOKE ALL ON SCHEMA knowledge FROM PUBLIC;
