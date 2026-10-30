import { defineConfig } from "@playwright/test";

// Browser end-to-end tests: the built app, a real API process (fake model, in-memory storage) and
// a stand-in sign-in provider, all on loopback. Open the app as localhost:5173, the one origin
// the provider and the API's CORS list accept.
const api = "http://127.0.0.1:8000";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: process.env["CI"] ? [["list"], ["html", { open: "never" }]] : "list",
  use: { baseURL: "http://localhost:5173", trace: "retain-on-failure" },
  webServer: [
    {
      command: "uv run python web/e2e/fake_idp.py",
      cwd: "..",
      url: "http://localhost:8180/realms/neuron/.well-known/openid-configuration",
      reuseExistingServer: !process.env["CI"],
    },
    {
      command: "uv run python -m uvicorn neuron_agent.api.main:app --host 127.0.0.1 --port 8000",
      cwd: "..",
      url: `${api}/health/live`,
      reuseExistingServer: !process.env["CI"],
      timeout: 120_000,
      env: {
        APP_ENV: "development",
        APP_DEFAULT_MODEL: "openai:gpt-5.4-mini",
        APP_OPENAI_API_KEY: "",
        OPENAI_API_KEY: "",
        APP_AUTH_MODE: "jwt",
        APP_AUTH_ISSUER: "http://localhost:8180/realms/neuron",
        APP_AUTH_AUDIENCE: "neuron-api",
        APP_AUTH_ALGORITHMS: '["ES256"]',
        APP_AUTH_JWKS_URL: "http://127.0.0.1:8180/realms/neuron/protocol/openid-connect/certs",
        APP_IDENTITY_HASH_KEY: "browser-e2e-identity-hash-key-not-a-secret",
        APP_CHECKPOINTER: "memory",
        APP_MEMORY_ENABLED: "true",
        APP_OTEL_ENABLED: "false",
        APP_ENABLE_LANGSMITH: "false",
        APP_FAKE_MODEL_TTFT_MS: "1",
        APP_RATE_LIMIT_ENABLED: "false",
        APP_USER_TOKEN_BUDGET: "10000000",
        APP_ALLOWED_HOSTS: '["localhost","127.0.0.1"]',
        APP_CORS_ALLOWED_ORIGINS: '["http://localhost:5173"]',
      },
    },
    {
      command: "npx vite build && npx vite preview --host 127.0.0.1 --port 5173 --strictPort",
      url: "http://localhost:5173/",
      reuseExistingServer: !process.env["CI"],
      timeout: 120_000,
      env: {
        VITE_API_URL: api,
        VITE_OIDC_ISSUER: "http://localhost:8180/realms/neuron",
        VITE_OIDC_CLIENT_ID: "neuron-web",
      },
    },
  ],
});
