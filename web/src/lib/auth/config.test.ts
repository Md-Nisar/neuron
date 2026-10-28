import { describe, expect, it } from "vitest";

import { ConfigError, loadAuthConfig, sanitizeReturnTo } from "./config";

const ORIGIN = "http://localhost:5173";

describe("loadAuthConfig", () => {
  it("defaults to the development Keycloak and this origin's root for both redirects", () => {
    expect(loadAuthConfig({}, ORIGIN)).toEqual({
      issuer: "http://localhost:8180/realms/neuron",
      clientId: "neuron-web",
      redirectUri: "http://localhost:5173/",
      postLogoutRedirectUri: "http://localhost:5173/",
      scope: "openid profile",
    });
  });

  it("derives the redirect from the page origin only, never from a setting or the URL", () => {
    const config = loadAuthConfig(
      { VITE_OIDC_ISSUER: "https://id.example/realms/x" },
      "https://app.example",
    );

    expect(config.redirectUri).toBe("https://app.example/");
  });

  it.each([
    "https://id.example/realms/x",
    "http://localhost:8180/realms/x",
    "http://127.0.0.1:8180/r",
  ])("accepts %s", (issuer) => {
    expect(() => loadAuthConfig({ VITE_OIDC_ISSUER: issuer }, ORIGIN)).not.toThrow();
  });

  it.each([
    "http://id.example/realms/x",
    "ftp://localhost/x",
    "not a url",
    "https://user:pass@id.example/x",
    "https://id.example/x?a=1",
    "https://id.example/x#frag",
  ])("refuses the issuer %s", (issuer) => {
    expect(() => loadAuthConfig({ VITE_OIDC_ISSUER: issuer }, ORIGIN)).toThrow(ConfigError);
  });
});

describe("sanitizeReturnTo", () => {
  it.each([
    ["/", "/"],
    ["/chat", "/chat"],
    ["/chat?thread=1&x=%20y#top", "/chat?thread=1&x=%20y#top"],
  ])("keeps the local path %s", (input, expected) => {
    expect(sanitizeReturnTo(input, ORIGIN)).toBe(expected);
  });

  it.each([
    "https://evil.example/",
    "//evil.example/phish",
    "///evil.example",
    "/\\evil.example",
    "\\\\evil.example",
    "javascript:alert(1)",
    "data:text/html,x",
    "chat",
    "",
    "/ok\r\nSet-Cookie: a=b",
    "/ok\u0000",
    "/\t/evil.example",
  ])("falls back to / for %j", (input) => {
    expect(sanitizeReturnTo(input, ORIGIN)).toBe("/");
  });
});
