import { describe, expect, it } from "vitest";

import { challengeS256, randomToken } from "./pkce";

describe("challengeS256", () => {
  it("matches the RFC 7636 appendix B test vector", async () => {
    const verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk";

    expect(await challengeS256(verifier)).toBe("E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM");
  });
});

describe("randomToken", () => {
  it("is 256 bits, URL-safe and unpadded", () => {
    const token = randomToken();

    expect(token).toMatch(/^[A-Za-z0-9_-]{43}$/);
  });

  it("does not repeat", () => {
    const tokens = new Set(Array.from({ length: 200 }, () => randomToken()));

    expect(tokens.size).toBe(200);
  });
});
