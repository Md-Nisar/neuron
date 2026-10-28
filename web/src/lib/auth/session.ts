import { sanitizeReturnTo, type AuthConfig } from "./config";
import { discover, type Endpoints } from "./discovery";
import { checkIdToken } from "./idToken";
import { challengeS256, randomToken } from "./pkce";

export type AuthStatus = "loading" | "signed_out" | "signed_in" | "expired" | "error";

/** Fixed, UI-safe reasons. Provider text never reaches the UI; only these codes do. */
export type AuthErrorCode =
  | "no_transaction"
  | "state_mismatch"
  | "issuer_mismatch"
  | "provider_error"
  | "token_exchange_failed"
  | "invalid_token_response"
  | "invalid_id_token"
  | "discovery_failed"
  | "network";

export class AuthError extends Error {
  constructor(readonly code: AuthErrorCode) {
    super(`sign-in failed: ${code}`);
    this.name = "AuthError";
  }
}

export interface AuthSnapshot {
  status: AuthStatus;
  displayName: string | null;
  error: AuthErrorCode | null;
}

interface Transaction {
  state: string;
  nonce: string;
  verifier: string;
  returnTo: string;
  expiresAt: number;
}

type StorageLike = Pick<Storage, "getItem" | "setItem" | "removeItem">;

export interface SessionDeps {
  config: AuthConfig;
  fetch?: typeof fetch;
  /** Holds only the one-time sign-in transaction across the redirect, never a token. */
  storage?: StorageLike;
  navigate?: (url: string) => void;
  replaceUrl?: (url: string) => void;
  now?: () => number;
  setTimer?: (callback: () => void, ms: number) => unknown;
  clearTimer?: (handle: unknown) => void;
  /** Loads an authorization URL in a hidden frame and resolves with the callback URL. */
  runFrame?: (url: string) => Promise<string>;
}

const TRANSACTION_KEY = "neuron.auth.transaction";
const TRANSACTION_TTL_MS = 10 * 60 * 1000;
/** Renew (or ask to sign in again) this long before the access token expires. */
const EXPIRY_MARGIN_SECONDS = 30;
const MAX_LIFETIME_SECONDS = 24 * 60 * 60;

const SIGNED_OUT: AuthSnapshot = { status: "signed_out", displayName: null, error: null };

/**
 * Authorization Code + PKCE (S256) against the identity provider (ADR 0010, decision 5).
 *
 * The access token lives in a private field only: never in storage, a cookie, the URL or a
 * log. The refresh token the provider may return is never read. `sessionStorage` carries just
 * the one-time transaction (state, nonce, PKCE verifier) across the full-page redirect; it is
 * deleted the moment the callback arrives, whether or not it succeeds, and expires after 10
 * minutes, so a replayed callback finds nothing.
 */
export class AuthSession {
  readonly #config: AuthConfig;
  readonly #fetch: typeof fetch;
  readonly #storage: StorageLike;
  readonly #navigate: (url: string) => void;
  readonly #replaceUrl: (url: string) => void;
  readonly #now: () => number;
  readonly #setTimer: (callback: () => void, ms: number) => unknown;
  readonly #clearTimer: (handle: unknown) => void;
  readonly #runFrame: ((url: string) => Promise<string>) | undefined;

  #endpoints: Promise<Endpoints> | null = null;
  #init: Promise<void> | null = null;
  #accessToken: string | null = null;
  #idToken: string | null = null;
  #expiresAt = 0;
  #timer: unknown = null;
  #snapshot: AuthSnapshot = { status: "loading", displayName: null, error: null };
  readonly #listeners = new Set<() => void>();

  constructor(deps: SessionDeps) {
    this.#config = deps.config;
    this.#fetch = deps.fetch ?? ((...args) => fetch(...args));
    this.#storage = deps.storage ?? window.sessionStorage;
    this.#navigate =
      deps.navigate ??
      ((url) => {
        window.location.assign(url);
      });
    this.#replaceUrl =
      deps.replaceUrl ??
      ((url) => {
        window.history.replaceState(null, "", url);
      });
    this.#now = deps.now ?? (() => Date.now());
    this.#setTimer = deps.setTimer ?? ((callback, ms) => window.setTimeout(callback, ms));
    this.#clearTimer =
      deps.clearTimer ??
      ((handle) => {
        window.clearTimeout(handle as number);
      });
    this.#runFrame = deps.runFrame;
  }

  // --- observable state (for useSyncExternalStore) -------------------------------------

  subscribe = (listener: () => void): (() => void) => {
    this.#listeners.add(listener);
    return () => this.#listeners.delete(listener);
  };

  getSnapshot = (): AuthSnapshot => this.#snapshot;

  #set(next: AuthSnapshot): void {
    this.#snapshot = next;
    for (const listener of this.#listeners) listener();
  }

  /** The access token for an API call, or null if there is none or it has run out. */
  getAccessToken(): string | null {
    return this.#accessToken !== null && this.#now() < this.#expiresAt ? this.#accessToken : null;
  }

  // --- start-up -----------------------------------------------------------------------

  /** Handle a sign-in callback if `href` is one. Safe to call twice (React StrictMode). */
  init(href: string): Promise<void> {
    this.#init ??= this.#initialise(href);
    return this.#init;
  }

  async #initialise(href: string): Promise<void> {
    const url = new URL(href);
    if (!url.searchParams.has("code") && !url.searchParams.has("error")) {
      this.#set(SIGNED_OUT);
      return;
    }
    // First thing: take the code and state out of the address bar and the history.
    this.#replaceUrl(url.origin + url.pathname);
    try {
      const transaction = this.#takeTransaction();
      const returnTo = await this.#complete(url.searchParams, transaction);
      this.#replaceUrl(returnTo);
    } catch (error) {
      this.#fail(error);
    }
  }

  // --- sign in / out ------------------------------------------------------------------

  /** Send the browser to the provider's login page. `returnTo` is reduced to a local path. */
  async signIn(returnTo = "/"): Promise<void> {
    try {
      const endpoints = await this.#discovered();
      const { transaction, challenge } = await this.#newTransaction(returnTo);
      this.#storage.setItem(TRANSACTION_KEY, JSON.stringify(transaction));
      this.#navigate(this.#authorizationUrl(endpoints, transaction, challenge, false));
    } catch (error) {
      this.#fail(error);
    }
  }

  /** Forget the tokens first, then end the provider's session. */
  async signOut(): Promise<void> {
    const idToken = this.#idToken;
    this.#forgetTokens();
    this.#storage.removeItem(TRANSACTION_KEY);
    this.#set(SIGNED_OUT);
    try {
      const { endSession } = await this.#discovered();
      if (endSession === null) return;
      const url = new URL(endSession);
      url.searchParams.set("client_id", this.#config.clientId);
      url.searchParams.set("post_logout_redirect_uri", this.#config.postLogoutRedirectUri);
      if (idToken !== null) url.searchParams.set("id_token_hint", idToken);
      this.#navigate(url.href);
    } catch {
      // Already signed out locally; the provider's session ends on its own timeout.
    }
  }

  // --- renewal ------------------------------------------------------------------------

  /**
   * Try to get a fresh access token through the provider's own session (hidden frame,
   * `prompt=none`). No refresh token is involved. Returns false on any failure; the caller
   * then asks the user to sign in again (ADR 0010, open question 2).
   */
  async renew(): Promise<boolean> {
    if (this.#runFrame === undefined) return false;
    try {
      const endpoints = await this.#discovered();
      const { transaction, challenge } = await this.#newTransaction("/");
      const callback = new URL(
        await this.#runFrame(this.#authorizationUrl(endpoints, transaction, challenge, true)),
      );
      if (callback.origin !== new URL(this.#config.redirectUri).origin) return false;
      await this.#complete(callback.searchParams, transaction);
      return true;
    } catch {
      return false;
    }
  }

  // --- internals ----------------------------------------------------------------------

  #discovered(): Promise<Endpoints> {
    this.#endpoints ??= discover(this.#config, this.#fetch).catch(() => {
      this.#endpoints = null;
      throw new AuthError("discovery_failed");
    });
    return this.#endpoints;
  }

  async #newTransaction(
    returnTo: string,
  ): Promise<{ transaction: Transaction; challenge: string }> {
    const verifier = randomToken();
    const transaction: Transaction = {
      state: randomToken(),
      nonce: randomToken(),
      verifier,
      returnTo: sanitizeReturnTo(returnTo, this.#config.redirectUri),
      expiresAt: this.#now() + TRANSACTION_TTL_MS,
    };
    return { transaction, challenge: await challengeS256(verifier) };
  }

  #authorizationUrl(
    endpoints: Endpoints,
    transaction: Transaction,
    challenge: string,
    silent: boolean,
  ): string {
    const url = new URL(endpoints.authorization);
    url.searchParams.set("response_type", "code");
    url.searchParams.set("client_id", this.#config.clientId);
    url.searchParams.set("redirect_uri", this.#config.redirectUri);
    url.searchParams.set("scope", this.#config.scope);
    url.searchParams.set("state", transaction.state);
    url.searchParams.set("nonce", transaction.nonce);
    url.searchParams.set("code_challenge", challenge);
    url.searchParams.set("code_challenge_method", "S256");
    if (silent) url.searchParams.set("prompt", "none");
    return url.href;
  }

  /** Read and delete the stored transaction. It is gone even if it turns out to be invalid. */
  #takeTransaction(): Transaction {
    const raw = this.#storage.getItem(TRANSACTION_KEY);
    this.#storage.removeItem(TRANSACTION_KEY);
    let parsed: unknown;
    try {
      parsed = raw === null ? null : JSON.parse(raw);
    } catch {
      parsed = null;
    }
    const t = parsed as Partial<Transaction> | null;
    if (
      typeof t?.state !== "string" ||
      typeof t.nonce !== "string" ||
      typeof t.verifier !== "string" ||
      typeof t.returnTo !== "string" ||
      typeof t.expiresAt !== "number" ||
      t.expiresAt < this.#now()
    ) {
      throw new AuthError("no_transaction");
    }
    return t as Transaction;
  }

  async #complete(params: URLSearchParams, transaction: Transaction): Promise<string> {
    if (params.get("state") !== transaction.state) throw new AuthError("state_mismatch");
    // RFC 9207: a response that names a different issuer is a mix-up attack.
    const issuer = params.get("iss");
    if (issuer !== null && issuer !== this.#config.issuer) throw new AuthError("issuer_mismatch");
    const code = params.get("code");
    if (params.has("error") || code === null || code === "" || code.length > 2048) {
      throw new AuthError("provider_error");
    }

    const endpoints = await this.#discovered();
    let response: Response;
    try {
      response = await this.#fetch(endpoints.token, {
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded",
          Accept: "application/json",
        },
        body: new URLSearchParams({
          grant_type: "authorization_code",
          code,
          redirect_uri: this.#config.redirectUri,
          client_id: this.#config.clientId,
          code_verifier: transaction.verifier,
        }),
        credentials: "omit",
        cache: "no-store",
        redirect: "error",
      });
    } catch {
      throw new AuthError("network");
    }
    if (!response.ok) throw new AuthError("token_exchange_failed");

    let body: unknown;
    try {
      body = await response.json();
    } catch {
      throw new AuthError("invalid_token_response");
    }
    const tokens = body as Record<string, unknown> | null;
    const accessToken = tokens?.["access_token"];
    const idToken = tokens?.["id_token"];
    const lifetime = tokens?.["expires_in"];
    const tokenType = tokens?.["token_type"];
    // `refresh_token`, if present, is deliberately never read or kept.
    if (
      typeof accessToken !== "string" ||
      accessToken === "" ||
      typeof idToken !== "string" ||
      typeof tokenType !== "string" ||
      tokenType.toLowerCase() !== "bearer" ||
      typeof lifetime !== "number" ||
      !Number.isFinite(lifetime) ||
      lifetime <= 0
    ) {
      throw new AuthError("invalid_token_response");
    }
    let identity;
    try {
      identity = checkIdToken(idToken, this.#config, transaction.nonce, this.#now() / 1000);
    } catch {
      throw new AuthError("invalid_id_token");
    }

    this.#forgetTokens();
    this.#accessToken = accessToken;
    this.#idToken = idToken;
    const seconds = Math.min(lifetime, MAX_LIFETIME_SECONDS);
    this.#expiresAt = this.#now() + seconds * 1000;
    this.#timer = this.#setTimer(
      () => void this.#expiring(),
      Math.max(0, seconds - EXPIRY_MARGIN_SECONDS) * 1000,
    );
    this.#set({ status: "signed_in", displayName: identity.displayName, error: null });
    return transaction.returnTo;
  }

  async #expiring(): Promise<void> {
    if (await this.renew()) return;
    this.#forgetTokens();
    this.#set({ status: "expired", displayName: null, error: null });
  }

  #forgetTokens(): void {
    if (this.#timer !== null) this.#clearTimer(this.#timer);
    this.#timer = null;
    this.#accessToken = null;
    this.#idToken = null;
    this.#expiresAt = 0;
  }

  #fail(error: unknown): void {
    this.#forgetTokens();
    const code: AuthErrorCode = error instanceof AuthError ? error.code : "network";
    this.#set({ status: "error", displayName: null, error: code });
  }
}
