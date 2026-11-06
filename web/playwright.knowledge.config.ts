import { defineConfig } from "@playwright/test";

import base from "./playwright.config";

// The knowledge flow (RAG-06.01): the same stand-in sign-in provider, API and built app as
// `playwright.config.ts`, with the API on Postgres and knowledge on. Postgres (with pgvector and
// the roles of `deploy/reference/init-roles.sql`), `setup` and `neuron-worker` must already be
// running, with the `APP_POSTGRES_*` DSNs and the settings below in the environment (the CI job
// `web-e2e-knowledge` does all of it). The fake embedding provider makes no network call.
export const KNOWLEDGE_ENV = {
  APP_CHECKPOINTER: "postgres",
  APP_KNOWLEDGE_ENABLED: "true",
  APP_KNOWLEDGE_EMBEDDING_PROVIDER: "fake",
};

const servers = Array.isArray(base.webServer) ? base.webServer : [];

export default defineConfig({
  ...base,
  // The default config leaves this spec out; this one runs only it.
  testIgnore: [],
  testMatch: /knowledge\.spec\.ts/,
  webServer: servers.map((server) =>
    server.url?.endsWith("/health/live") === true
      ? // The API's own logs (stdout) show in CI when the flow fails.
        { ...server, env: { ...server.env, ...KNOWLEDGE_ENV }, stdout: "pipe" as const }
      : server,
  ),
});
