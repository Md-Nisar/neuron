import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "@/App";
import { maxPromptChars } from "@/features/chat/limits";
import {
  AuthProvider,
  AuthSession,
  ConfigError,
  loadAuthConfig,
  reportFrameCallback,
  runAuthFrame,
} from "@/lib/auth";
import { ApiConfigError, loadApiUrl } from "@/lib/api";
import "@/index.css";

const root = document.getElementById("root");
if (root === null) {
  throw new Error("missing #root element");
}

// A hidden silent-renew frame only reports its callback URL to the page that opened it.
if (!reportFrameCallback()) {
  try {
    const session = new AuthSession({
      config: loadAuthConfig(import.meta.env, window.location.origin),
      runFrame: (url) => runAuthFrame(url),
    });
    createRoot(root).render(
      <StrictMode>
        <AuthProvider session={session}>
          <App apiUrl={loadApiUrl(import.meta.env)} maxChars={maxPromptChars(import.meta.env)} />
        </AuthProvider>
      </StrictMode>,
    );
  } catch (error) {
    if (!(error instanceof ConfigError || error instanceof ApiConfigError)) throw error;
    root.textContent = "The application is not configured correctly.";
  }
}
