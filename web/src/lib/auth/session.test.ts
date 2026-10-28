import { afterEach, describe, expect, it, vi } from "vitest";

import { CONFIG, ENDPOINTS, FakeProvider, SECRETS } from "@/test/oidc";

import { AuthSession, type SessionDeps } from "./session";

class MemoryStorage {
  readonly map = new Map<string, string>();
  getItem = (key: string): string | null => this.map.get(key) ?? null;
  setItem = (key: string, value: string): void => {
    this.map.set(key, value);
  };
  removeItem = (key: string): void => {
    this.map.delete(key);
  };
}

interface Timer {
  callback: () => void;
  ms: number;
  cleared: boolean;
}

function harness(extra: Partial<SessionDeps> = {}) {
  const provider = new FakeProvider();
  const storage = new MemoryStorage();
  const navigations: string[] = [];
  const urls: string[] = [];
  const timers: Timer[] = [];
  const make = (more: Partial<SessionDeps> = {}) =>
    new AuthSession({
      config: CONFIG,
      fetch: provider.fetch,
      storage,
      navigate: (url) => navigations.push(url),
      replaceUrl: (url) => urls.push(url),
      setTimer: (callback, ms) => {
        const timer = { callback, ms, cleared: false };
        timers.push(timer);
        return timer;
      },
      clearTimer: (handle) => {
        (handle as Timer).cleared = true;
      },
      ...extra,
      ...more,
    });
  /** Sign in, let the provider authorise, and return the callback URL the browser comes back to. */
  async function login(session: AuthSession, returnTo = "/") {
    await session.signIn(returnTo);
    const authorizationUrl = navigations.at(-1) ?? "";
    provider.authorize(authorizationUrl);
    return { authorizationUrl, callback: provider.callbackUrl() };
  }
  return { provider, storage, navigations, urls, timers, make, login };
}

const status = (session: AuthSession) => session.getSnapshot().status;

afterEach(() => {
  vi.restoreAllMocks();
});

describe("sign-in redirect", () => {
  it("sends Authorization Code + PKCE S256 with fixed redirect, scope, state and nonce", async () => {
    const h = harness();
    const { authorizationUrl } = await h.login(h.make());
    const url = new URL(authorizationUrl);

    expect(`${url.origin}${url.pathname}`).toBe(ENDPOINTS.authorization);
    expect(Object.fromEntries(url.searchParams)).toMatchObject({
      response_type: "code",
      client_id: "neuron-web",
      redirect_uri: CONFIG.redirectUri,
      scope: "openid profile",
      code_challenge_method: "S256",
    });
    expect(url.searchParams.get("state")?.length).toBeGreaterThanOrEqual(43);
    expect(url.searchParams.get("nonce")?.length).toBeGreaterThanOrEqual(43);
    expect(url.searchParams.get("state")).not.toBe(url.searchParams.get("nonce"));
    expect(url.searchParams.has("prompt")).toBe(false);
  });

  it("keeps only the one-time transaction in storage, never a token", async () => {
    const h = harness();
    await h.login(h.make(), "/chat");

    expect([...h.storage.map.keys()]).toEqual(["neuron.auth.transaction"]);
  });

  it("refuses to start when the provider's configuration is not trustworthy", async () => {
    const h = harness();
    h.provider.discoveryDocument = {
      ...h.provider.discoveryDocument,
      issuer: "https://evil.example",
    };
    const session = h.make();
    await session.signIn();

    expect(h.navigations).toEqual([]);
    expect(session.getSnapshot()).toMatchObject({ status: "error", error: "discovery_failed" });
  });
});

describe("callback", () => {
  it("exchanges the code with the matching PKCE verifier and signs in, in memory only", async () => {
    const h = harness();
    const { callback } = await h.login(h.make(), "/chat?x=1");
    const reloaded = h.make();
    await reloaded.init(callback);

    expect(reloaded.getSnapshot()).toEqual({
      status: "signed_in",
      displayName: "alice",
      error: null,
    });
    expect(reloaded.getAccessToken()).toBe(SECRETS.access[0]);
    expect(h.provider.tokenRequests).toHaveLength(1);
    // The address bar is cleaned first, then sent to the local page the user asked for.
    expect(h.urls).toEqual(["http://localhost:3000/", "/chat?x=1"]);
    expect(h.storage.map.size).toBe(0);
  });

  it("rejects a callback whose state does not match, without calling the token endpoint", async () => {
    const h = harness();
    await h.login(h.make());
    const forged = h.provider.callbackUrl({ state: "attacker-chosen" });
    const session = h.make();
    await session.init(forged);

    expect(session.getSnapshot()).toMatchObject({ status: "error", error: "state_mismatch" });
    expect(h.provider.tokenRequests).toHaveLength(0);
    expect(session.getAccessToken()).toBeNull();
  });

  it("is single-use: the transaction is gone after a failed callback and after a good one", async () => {
    const h = harness();
    const { callback } = await h.login(h.make());
    await h.make().init(callback);
    const replay = h.make();
    await replay.init(callback);

    expect(replay.getSnapshot()).toMatchObject({ status: "error", error: "no_transaction" });
    expect(h.provider.tokenRequests).toHaveLength(1);
  });

  it("deletes the transaction even when the callback is bad", async () => {
    const h = harness();
    await h.login(h.make());
    await h.make().init(h.provider.callbackUrl({ state: "wrong" }));

    expect(h.storage.map.size).toBe(0);
  });

  it("rejects an expired transaction", async () => {
    let now = 1_000_000;
    const h = harness({ now: () => now });
    const { callback } = await h.login(h.make());
    now += 11 * 60 * 1000;
    const session = h.make();
    await session.init(callback);

    expect(session.getSnapshot()).toMatchObject({ status: "error", error: "no_transaction" });
  });

  it("rejects a response that names a different issuer (mix-up)", async () => {
    const h = harness();
    await h.login(h.make());
    const session = h.make();
    await session.init(h.provider.callbackUrl({ iss: "https://evil.example/realms/neuron" }));

    expect(session.getSnapshot()).toMatchObject({ status: "error", error: "issuer_mismatch" });
    expect(h.provider.tokenRequests).toHaveLength(0);
  });

  it("shows a fixed reason for a provider error, never its text", async () => {
    const h = harness();
    await h.login(h.make());
    const url = new URL(h.provider.callbackUrl());
    url.searchParams.delete("code");
    url.searchParams.set("error", "access_denied");
    url.searchParams.set("error_description", "<script>alert(1)</script>");
    const session = h.make();
    await session.init(url.href);

    expect(session.getSnapshot()).toEqual({
      status: "error",
      displayName: null,
      error: "provider_error",
    });
  });

  it("handles a callback once even if started twice (React StrictMode)", async () => {
    const h = harness();
    const { callback } = await h.login(h.make());
    const session = h.make();
    await Promise.all([session.init(callback), session.init(callback)]);

    expect(h.provider.tokenRequests).toHaveLength(1);
    expect(status(session)).toBe("signed_in");
  });

  it("is signed out, with no network call, on a normal page load", async () => {
    const h = harness();
    const session = h.make();
    await session.init("http://localhost:3000/");

    expect(status(session)).toBe("signed_out");
    expect(h.provider.tokenRequests).toHaveLength(0);
    expect(h.urls).toEqual([]);
  });

  it.each([
    ["//evil.example/phish", "/"],
    ["https://evil.example/", "/"],
    ["/\\evil.example", "/"],
    ["javascript:alert(1)", "/"],
    ["/ok/path?q=1#frag", "/ok/path?q=1#frag"],
  ])("never redirects off-site after sign-in (returnTo %s)", async (returnTo, expected) => {
    const h = harness();
    const { callback } = await h.login(h.make(), returnTo);
    await h.make().init(callback);

    expect(h.urls.at(-1)).toBe(expected);
  });
});

describe("token validation", () => {
  async function failWith(mutate: (provider: FakeProvider) => void) {
    const h = harness();
    const { callback } = await h.login(h.make());
    mutate(h.provider);
    const session = h.make();
    await session.init(callback);
    return session;
  }

  it.each([
    ["a nonce that was not ours", (p: FakeProvider) => (p.idClaims = { nonce: "someone-elses" })],
    ["another issuer", (p: FakeProvider) => (p.idClaims = { iss: "https://evil.example" })],
    ["another audience", (p: FakeProvider) => (p.idClaims = { aud: "other-client" })],
    ["an expired ID token", (p: FakeProvider) => (p.idClaims = { exp: 1 })],
    [
      "multiple audiences without azp",
      (p: FakeProvider) => (p.idClaims = { aud: ["neuron-web", "x"] }),
    ],
  ])("rejects an ID token with %s and keeps no token", async (_name, mutate) => {
    const session = await failWith((p) => {
      mutate(p);
    });

    expect(session.getSnapshot()).toMatchObject({ status: "error", error: "invalid_id_token" });
    expect(session.getAccessToken()).toBeNull();
  });

  it.each([
    ["a missing access token", { access_token: undefined }],
    ["a non-bearer token type", { token_type: "mac" }],
    ["a missing ID token", { id_token: undefined }],
    ["a zero lifetime", { expires_in: 0 }],
    ["a non-numeric lifetime", { expires_in: "300" }],
  ])("rejects a token response with %s", async (_name, body) => {
    const session = await failWith((p) => {
      p.tokenBody = body;
    });

    expect(session.getSnapshot()).toMatchObject({
      status: "error",
      error: "invalid_token_response",
    });
    expect(session.getAccessToken()).toBeNull();
  });

  it("reports a refused code exchange without echoing the provider's body", async () => {
    const session = await failWith((p) => {
      p.tokenStatus = 500;
    });

    expect(session.getSnapshot()).toMatchObject({
      status: "error",
      error: "token_exchange_failed",
    });
  });
});

describe("expiry and silent renew", () => {
  async function signedIn(extra: Partial<SessionDeps> = {}) {
    const h = harness(extra);
    const { callback } = await h.login(h.make(extra));
    const session = h.make(extra);
    await session.init(callback);
    return { h, session };
  }

  it("schedules the check 30 seconds before the token runs out", async () => {
    const { h } = await signedIn();

    expect(h.timers.at(-1)?.ms).toBe((300 - 30) * 1000);
  });

  it("asks the user to sign in again when it expires and cannot renew", async () => {
    const { h, session } = await signedIn();
    h.timers.at(-1)?.callback();
    await vi.waitFor(() => {
      expect(status(session)).toBe("expired");
    });

    expect(session.getAccessToken()).toBeNull();
  });

  it("renews through a hidden frame with prompt=none and keeps the user signed in", async () => {
    const frames: string[] = [];
    const provider: { current?: FakeProvider } = {};
    const runFrame = (url: string): Promise<string> => {
      frames.push(url);
      provider.current?.authorize(url);
      return Promise.resolve(provider.current?.callbackUrl() ?? "");
    };
    const result = await signedIn({ runFrame });
    provider.current = result.h.provider;
    result.h.timers.at(-1)?.callback();
    await vi.waitFor(() => {
      expect(result.session.getAccessToken()).toBe(SECRETS.access[1]);
    });

    expect(new URL(frames[0] ?? "").searchParams.get("prompt")).toBe("none");
    expect(status(result.session)).toBe("signed_in");
    expect(result.h.timers.length).toBeGreaterThan(1);
  });

  it.each([
    ["the frame times out", () => Promise.reject(new Error("timeout"))],
    [
      "the provider says login_required",
      () => Promise.resolve(`${CONFIG.redirectUri}?error=login_required&state=x`),
    ],
    [
      "the frame returns another origin",
      () => Promise.resolve("https://evil.example/?code=x&state=y"),
    ],
  ])("falls back to the sign-in prompt when %s", async (_name, runFrame) => {
    const { h, session } = await signedIn({ runFrame });
    h.timers.at(-1)?.callback();
    await vi.waitFor(() => {
      expect(status(session)).toBe("expired");
    });

    expect(session.getAccessToken()).toBeNull();
  });

  it("stops handing out the token the moment it has expired", async () => {
    let now = 1_000_000;
    const { session } = await signedIn({ now: () => now });
    expect(session.getAccessToken()).not.toBeNull();
    now += 301 * 1000;

    expect(session.getAccessToken()).toBeNull();
  });
});

describe("sign-out", () => {
  it("clears memory first, then ends the provider session with the ID token as the hint", async () => {
    const h = harness();
    const { callback } = await h.login(h.make());
    const session = h.make();
    await session.init(callback);
    await session.signOut();

    const url = new URL(h.navigations.at(-1) ?? "");
    expect(`${url.origin}${url.pathname}`).toBe(ENDPOINTS.endSession);
    expect(url.searchParams.get("client_id")).toBe("neuron-web");
    expect(url.searchParams.get("post_logout_redirect_uri")).toBe(CONFIG.postLogoutRedirectUri);
    expect(url.searchParams.get("id_token_hint")).toBeTruthy();
    expect(url.href).not.toContain(SECRETS.access[0]);
    expect(session.getAccessToken()).toBeNull();
    expect(status(session)).toBe("signed_out");
    expect(h.timers.at(-1)?.cleared).toBe(true);
  });

  it("is signed out locally even if the provider cannot be reached", async () => {
    const h = harness();
    const { callback } = await h.login(h.make());
    const session = h.make();
    await session.init(callback);
    h.provider.discoveryDocument = {};
    const offline = h.make({ fetch: () => Promise.reject(new TypeError("offline")) });
    await offline.signOut();
    await session.signOut();

    expect(session.getAccessToken()).toBeNull();
    expect(status(session)).toBe("signed_out");
  });
});

describe("the access token never leaves memory", () => {
  it("is absent from storage, cookies, history, the URL and the console through sign-in, renew and sign-out", async () => {
    const written: string[] = [];
    const record = (...args: unknown[]): void => {
      written.push(args.map((v) => (typeof v === "string" ? v : JSON.stringify(v))).join(" "));
    };
    // Record every write, then let it through: the test must observe real behaviour.
    const realSetItem: (this: Storage, key: string, value: string) => void = Reflect.get(
      Storage.prototype,
      "setItem",
    );
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(function (
      this: Storage,
      key: string,
      value: string,
    ) {
      record(key, value);
      realSetItem.call(this, key, value);
    });
    vi.spyOn(Document.prototype, "cookie", "set").mockImplementation((value) => {
      record("cookie", value);
    });
    const realReplaceState = window.history.replaceState.bind(window.history);
    vi.spyOn(window.history, "replaceState").mockImplementation((data, unused, url) => {
      record("replaceState", url);
      realReplaceState(data, unused, url);
    });
    vi.spyOn(window.history, "pushState").mockImplementation((_data, _unused, url) => {
      record("pushState", url);
    });
    for (const method of ["log", "info", "warn", "error", "debug", "trace"] as const) {
      vi.spyOn(console, method).mockImplementation((...args: unknown[]) => {
        record(method, ...args);
      });
    }

    const navigations: string[] = [];
    const provider = new FakeProvider();
    const frameRun = (url: string): Promise<string> => {
      provider.authorize(url);
      return Promise.resolve(provider.callbackUrl());
    };
    const make = () =>
      new AuthSession({
        config: CONFIG,
        fetch: provider.fetch,
        navigate: (url) => navigations.push(url),
        runFrame: frameRun,
        setTimer: () => 0,
      });

    const first = make();
    await first.signIn("/chat");
    provider.authorize(navigations.at(-1) ?? "");
    const callback = provider.callbackUrl();
    const second = make();
    await second.init(callback);
    expect(second.getAccessToken()).toBe(SECRETS.access[0]);
    expect(await second.renew()).toBe(true);
    expect(second.getAccessToken()).toBe(SECRETS.access[1]);
    await second.signOut();

    const everything = [...written, ...navigations, window.location.href, document.cookie].join(
      "\n",
    );
    for (const secret of [...SECRETS.access, SECRETS.refresh]) {
      expect(everything).not.toContain(secret);
    }
    // The one-time transaction is gone, and nothing is left behind.
    expect(window.sessionStorage.length).toBe(0);
    expect(window.localStorage.length).toBe(0);
    expect(window.location.search).toBe("");
  });
});
