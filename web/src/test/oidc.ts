import type { AuthConfig } from "@/lib/auth";
import { challengeS256 } from "@/lib/auth/pkce";

export const CONFIG: AuthConfig = {
  issuer: "http://localhost:8180/realms/neuron",
  clientId: "neuron-web",
  redirectUri: "http://localhost:3000/",
  postLogoutRedirectUri: "http://localhost:3000/",
  scope: "openid profile",
};

const ORIGIN = "http://localhost:8180";
export const ENDPOINTS = {
  authorization: `${ORIGIN}/realms/neuron/protocol/openid-connect/auth`,
  token: `${ORIGIN}/realms/neuron/protocol/openid-connect/token`,
  endSession: `${ORIGIN}/realms/neuron/protocol/openid-connect/logout`,
};

function segment(value: unknown): string {
  return btoa(JSON.stringify(value)).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
}

/** An unsigned JWT-shaped ID token; the client checks claims, not the signature. */
export function makeIdToken(claims: Record<string, unknown>): string {
  return `${segment({ alg: "RS256" })}.${segment(claims)}.signature`;
}

export const SECRETS = {
  access: ["ACCESS-TOKEN-SECRET-1", "ACCESS-TOKEN-SECRET-2", "ACCESS-TOKEN-SECRET-3"],
  refresh: "REFRESH-TOKEN-SECRET",
};

/** A fake identity provider that enforces PKCE for real (it recomputes the S256 challenge). */
export class FakeProvider {
  state = "";
  nonce = "";
  challenge = "";
  issued = 0;
  tokenRequests: URLSearchParams[] = [];
  /** Override pieces of the ID token or the token response per test. */
  idClaims: Record<string, unknown> = {};
  tokenBody: Record<string, unknown> = {};
  tokenStatus = 200;
  discoveryDocument: Record<string, unknown> = {
    issuer: CONFIG.issuer,
    authorization_endpoint: ENDPOINTS.authorization,
    token_endpoint: ENDPOINTS.token,
    end_session_endpoint: ENDPOINTS.endSession,
  };

  /** The user's browser reaches the authorization endpoint: remember what it asked for. */
  authorize(authorizationUrl: string): void {
    const params = new URL(authorizationUrl).searchParams;
    this.state = params.get("state") ?? "";
    this.nonce = params.get("nonce") ?? "";
    this.challenge = params.get("code_challenge") ?? "";
  }

  callbackUrl(extra: Record<string, string> = {}): string {
    const url = new URL(CONFIG.redirectUri);
    url.searchParams.set("code", "the-code");
    url.searchParams.set("state", this.state);
    url.searchParams.set("iss", CONFIG.issuer);
    for (const [key, value] of Object.entries(extra)) url.searchParams.set(key, value);
    return url.href;
  }

  fetch: typeof fetch = async (input, init) => {
    const url = input instanceof URL ? input.href : typeof input === "string" ? input : input.url;
    if (url === `${CONFIG.issuer}/.well-known/openid-configuration`) {
      return Response.json(this.discoveryDocument);
    }
    if (url !== ENDPOINTS.token || !(init?.body instanceof URLSearchParams)) {
      return new Response("not found", { status: 404 });
    }
    const body = init.body;
    this.tokenRequests.push(body);
    const verifier = body.get("code_verifier") ?? "";
    const valid =
      body.get("grant_type") === "authorization_code" &&
      body.get("code") === "the-code" &&
      body.get("redirect_uri") === CONFIG.redirectUri &&
      body.get("client_id") === CONFIG.clientId &&
      (await challengeS256(verifier)) === this.challenge;
    if (!valid) return Response.json({ error: "invalid_grant" }, { status: 400 });
    if (this.tokenStatus !== 200)
      return Response.json({ error: "server_error" }, { status: this.tokenStatus });
    const access = SECRETS.access[this.issued++] ?? "ACCESS-TOKEN-SECRET-N";
    return Response.json({
      access_token: access,
      token_type: "Bearer",
      expires_in: 300,
      refresh_token: SECRETS.refresh,
      id_token: makeIdToken({
        iss: CONFIG.issuer,
        aud: CONFIG.clientId,
        nonce: this.nonce,
        exp: Math.floor(Date.now() / 1000) + 300,
        preferred_username: "alice",
        ...this.idClaims,
      }),
      ...this.tokenBody,
    });
  };
}
