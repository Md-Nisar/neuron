import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The dev server listens on loopback only. Open it as http://localhost:5173: that is the one
// origin the Keycloak realm allows (127.0.0.1 gets "Invalid parameter: redirect_uri").
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": new URL("./src", import.meta.url).pathname } },
  server: { host: "127.0.0.1", port: 5173, strictPort: true },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    // Whole-app keyboard and network tests take a few seconds each; leave room on a busy machine.
    testTimeout: 15_000,
  },
});
