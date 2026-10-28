/** Sign-in settings. Everything security-relevant here is fixed at build time, never read from the URL. */
export interface AuthConfig {
  issuer: string;
  clientId: string;
  /** Where the identity provider sends the browser back. Exactly this value, nothing derived. */
  redirectUri: string;
  postLogoutRedirectUri: string;
  scope: string;
}

export class ConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ConfigError";
  }
}

const LOOPBACK_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]"]);
const DEV_ISSUER = "http://localhost:8180/realms/neuron";

export interface AuthEnv {
  VITE_OIDC_ISSUER?: string | undefined;
  VITE_OIDC_CLIENT_ID?: string | undefined;
}

/**
 * Build the config for the page's own `origin`. The redirect URIs are that origin's root, so
 * they match the single URI the realm registers; an issuer over plain HTTP is accepted only on
 * a loopback host (the development Keycloak), mirroring the API's own rule.
 */
export function loadAuthConfig(env: AuthEnv, origin: string): AuthConfig {
  const issuer = (env.VITE_OIDC_ISSUER ?? DEV_ISSUER).replace(/\/+$/, "");
  let url: URL;
  try {
    url = new URL(issuer);
  } catch {
    throw new ConfigError("the OIDC issuer is not a URL");
  }
  const loopback = LOOPBACK_HOSTS.has(url.hostname);
  if (url.protocol !== "https:" && !(url.protocol === "http:" && loopback)) {
    throw new ConfigError("the OIDC issuer must use https (http only on loopback)");
  }
  if (url.username !== "" || url.password !== "" || url.search !== "" || url.hash !== "") {
    throw new ConfigError("the OIDC issuer must be a plain URL");
  }
  const root = new URL("/", origin).href;
  return {
    issuer,
    clientId: env.VITE_OIDC_CLIENT_ID ?? "neuron-web",
    redirectUri: root,
    postLogoutRedirectUri: root,
    scope: "openid profile",
  };
}

/**
 * Where to send the user after sign-in: only a path on this origin. Anything else (another
 * origin, a protocol-relative `//host`, a backslash trick, a `javascript:` URL, control
 * characters) falls back to `/`, so a crafted link cannot turn sign-in into an open redirect.
 */
export function sanitizeReturnTo(candidate: string, origin: string): string {
  // eslint-disable-next-line no-control-regex
  if (!candidate.startsWith("/") || /[\u0000-\u001f\u007f\\]/.test(candidate)) return "/";
  if (candidate.startsWith("//")) return "/";
  try {
    const url = new URL(candidate, origin);
    return url.origin === new URL(origin).origin ? url.pathname + url.search + url.hash : "/";
  } catch {
    return "/";
  }
}
