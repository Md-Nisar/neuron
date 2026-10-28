const LOOPBACK_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]"]);
const DEFAULT_API_URL = "http://127.0.0.1:8000";

export class ApiConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ApiConfigError";
  }
}

/**
 * The API origin the bearer token is sent to. HTTPS, or plain HTTP on loopback only (the
 * development API): the token is never offered to a clear-text remote host. No credentials,
 * path, query or fragment in the setting, so requests cannot be steered by the value.
 */
export function loadApiUrl(env: { VITE_API_URL?: string | undefined }): string {
  const raw = env.VITE_API_URL ?? DEFAULT_API_URL;
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    throw new ApiConfigError("the API URL is not a URL");
  }
  const secure =
    url.protocol === "https:" || (url.protocol === "http:" && LOOPBACK_HOSTS.has(url.hostname));
  if (!secure) throw new ApiConfigError("the API URL must use https (http only on loopback)");
  if (
    url.username !== "" ||
    url.password !== "" ||
    url.search !== "" ||
    url.hash !== "" ||
    url.pathname !== "/"
  ) {
    throw new ApiConfigError("the API URL must be an origin only");
  }
  return url.origin;
}
