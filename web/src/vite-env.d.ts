/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_OIDC_ISSUER?: string;
  readonly VITE_OIDC_CLIENT_ID?: string;
  readonly VITE_API_URL?: string;
  readonly VITE_MAX_PROMPT_CHARS?: string;
}
