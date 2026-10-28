import { describe, expect, it } from "vitest";

import { CONFIG, ENDPOINTS, FakeProvider } from "@/test/oidc";

import { discover, DiscoveryError } from "./discovery";

describe("discover", () => {
  it("returns the endpoints of a document that names the configured issuer", async () => {
    const provider = new FakeProvider();

    expect(await discover(CONFIG, provider.fetch)).toEqual(ENDPOINTS);
  });

  it("does not need an end-session endpoint", async () => {
    const provider = new FakeProvider();
    provider.discoveryDocument = { ...provider.discoveryDocument, end_session_endpoint: undefined };

    expect(await discover(CONFIG, provider.fetch)).toMatchObject({ endSession: null });
  });

  it.each([
    ["another issuer", { issuer: "https://evil.example" }],
    ["a token endpoint on another origin", { token_endpoint: "https://evil.example/token" }],
    [
      "an authorization endpoint on another origin",
      { authorization_endpoint: "https://evil.example/auth" },
    ],
    ["a missing token endpoint", { token_endpoint: undefined }],
    ["a relative endpoint", { token_endpoint: "/token" }],
    ["a non-string endpoint", { token_endpoint: 5 }],
  ])("rejects a document with %s", async (_name, change) => {
    const provider = new FakeProvider();
    provider.discoveryDocument = { ...provider.discoveryDocument, ...change };

    await expect(discover(CONFIG, provider.fetch)).rejects.toThrow(DiscoveryError);
  });

  it("ignores an end-session endpoint on another origin rather than using it", async () => {
    const provider = new FakeProvider();
    provider.discoveryDocument = {
      ...provider.discoveryDocument,
      end_session_endpoint: "https://evil.example/logout",
    };

    expect(await discover(CONFIG, provider.fetch)).toMatchObject({ endSession: null });
  });

  it.each([
    ["an HTTP error", () => Promise.resolve(new Response("x", { status: 500 }))],
    ["invalid JSON", () => Promise.resolve(new Response("not json", { status: 200 }))],
    ["a JSON array", () => Promise.resolve(Response.json([]))],
    ["a network failure", () => Promise.reject(new TypeError("offline"))],
  ])("fails closed on %s", async (_name, doFetch) => {
    await expect(discover(CONFIG, doFetch)).rejects.toThrow(DiscoveryError);
  });

  it("asks without credentials and refuses redirects", async () => {
    const seen: RequestInit[] = [];
    const provider = new FakeProvider();
    await discover(CONFIG, (input, init) => {
      seen.push(init ?? {});
      return provider.fetch(input, init);
    });

    expect(seen[0]).toMatchObject({ credentials: "omit", redirect: "error", cache: "no-store" });
  });
});
