import { describe, expect, it } from "vitest";

import { ApiConfigError, loadApiUrl } from "./api";

describe("loadApiUrl", () => {
  it("defaults to the development API on loopback", () => {
    expect(loadApiUrl({})).toBe("http://127.0.0.1:8000");
  });

  it.each([
    "https://api.example",
    "http://localhost:8000",
    "http://[::1]:8000",
    "http://127.0.0.1:9000/",
  ])("accepts %s", (url) => {
    expect(() => loadApiUrl({ VITE_API_URL: url })).not.toThrow();
  });

  it("normalises to the origin without a trailing slash", () => {
    expect(loadApiUrl({ VITE_API_URL: "https://api.example/" })).toBe("https://api.example");
  });

  it.each([
    "http://api.example",
    "http://10.0.0.5:8000",
    "ftp://localhost",
    "javascript:alert(1)",
    "not a url",
    "https://user:pw@api.example",
    "https://api.example/v1",
    "https://api.example/?x=1",
    "https://api.example/#frag",
  ])("refuses %s so the token is never sent there", (url) => {
    expect(() => loadApiUrl({ VITE_API_URL: url })).toThrow(ApiConfigError);
  });
});
