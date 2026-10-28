import type { AuthConfig } from "./config";

export class IdTokenError extends Error {
  constructor() {
    super("the ID token was rejected");
    this.name = "IdTokenError";
  }
}

const CLOCK_SKEW_SECONDS = 60;

function decodePayload(token: string): Record<string, unknown> {
  const parts = token.split(".");
  const payload = parts[1];
  if (parts.length !== 3 || payload === undefined) throw new IdTokenError();
  try {
    const padded = payload.replaceAll("-", "+").replaceAll("_", "/");
    const binary = atob(padded.padEnd(Math.ceil(padded.length / 4) * 4, "="));
    const json = new TextDecoder().decode(Uint8Array.from(binary, (c) => c.charCodeAt(0)));
    const claims: unknown = JSON.parse(json);
    if (typeof claims !== "object" || claims === null || Array.isArray(claims)) {
      throw new IdTokenError();
    }
    return claims as Record<string, unknown>;
  } catch {
    throw new IdTokenError();
  }
}

export interface IdentityClaims {
  /** A display name for the UI. Untrusted text: render it as text, bounded. */
  displayName: string | null;
}

/**
 * Check the ID token from the token endpoint (OIDC Core 3.1.3.7). It arrived over TLS directly
 * from the provider's token endpoint, so its signature is not re-verified here (the spec allows
 * this); what binds it to this sign-in is the issuer, audience, expiry and the one-time nonce.
 * The API still verifies the *access* token's signature itself on every request.
 */
export function checkIdToken(
  idToken: string,
  config: AuthConfig,
  expectedNonce: string,
  nowSeconds: number,
): IdentityClaims {
  const claims = decodePayload(idToken);
  const audience = claims["aud"];
  const audiences = typeof audience === "string" ? [audience] : audience;
  const exp = claims["exp"];
  if (
    claims["iss"] !== config.issuer ||
    !Array.isArray(audiences) ||
    !audiences.includes(config.clientId) ||
    (audiences.length > 1 && claims["azp"] !== config.clientId) ||
    claims["nonce"] !== expectedNonce ||
    typeof exp !== "number" ||
    exp + CLOCK_SKEW_SECONDS < nowSeconds
  ) {
    throw new IdTokenError();
  }
  const name = claims["preferred_username"] ?? claims["name"];
  return { displayName: typeof name === "string" && name !== "" ? name.slice(0, 64) : null };
}
