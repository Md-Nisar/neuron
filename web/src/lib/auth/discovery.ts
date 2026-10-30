import type { AuthConfig } from "./config";

export interface Endpoints {
  authorization: string;
  token: string;
  /** Absent if the provider offers no RP-initiated logout. */
  endSession: string | null;
}

export class DiscoveryError extends Error {
  constructor() {
    super("could not read the identity provider's configuration");
    this.name = "DiscoveryError";
  }
}

function sameOrigin(candidate: unknown, issuer: URL): string | null {
  if (typeof candidate !== "string") return null;
  try {
    const url = new URL(candidate);
    return url.origin === issuer.origin ? url.href : null;
  } catch {
    return null;
  }
}

/**
 * Read the provider's endpoints. The document must name the configured issuer, and every
 * endpoint must be on the issuer's origin: a tampered document cannot send the user, the
 * authorization code or the PKCE verifier to another host.
 */
export async function discover(
  config: AuthConfig,
  doFetch: typeof fetch = fetch,
): Promise<Endpoints> {
  const issuer = new URL(config.issuer);
  let document: unknown;
  try {
    const response = await doFetch(`${config.issuer}/.well-known/openid-configuration`, {
      credentials: "omit",
      cache: "no-store",
      redirect: "error",
    });
    if (!response.ok) throw new DiscoveryError();
    document = await response.json();
  } catch {
    throw new DiscoveryError();
  }
  if (typeof document !== "object" || document === null) throw new DiscoveryError();
  const record = document as Record<string, unknown>;
  const authorization = sameOrigin(record["authorization_endpoint"], issuer);
  const token = sameOrigin(record["token_endpoint"], issuer);
  if (record["issuer"] !== config.issuer || authorization === null || token === null) {
    throw new DiscoveryError();
  }
  return { authorization, token, endSession: sameOrigin(record["end_session_endpoint"], issuer) };
}
