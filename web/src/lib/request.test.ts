import { describe, expect, it, vi } from "vitest";

import { jsonResponse } from "@/test/sse";

import { ApiError, apiRequest } from "./request";

const base = { baseUrl: "http://127.0.0.1:8000", token: "tok-1" };
const respond =
  (response: Response): typeof fetch =>
  () =>
    Promise.resolve(response);

async function failure(response: Response): Promise<ApiError> {
  try {
    await apiRequest({ ...base, path: "/v1/me/memories", method: "GET", fetch: respond(response) });
  } catch (error) {
    if (error instanceof ApiError) return error;
    throw error;
  }
  throw new Error("expected an ApiError");
}

describe("apiRequest", () => {
  it("sends the token in a header only, to the API origin, without cookies or caching", async () => {
    const fetchSpy = vi.fn<typeof fetch>(() => Promise.resolve(jsonResponse(200, { ok: true })));
    await apiRequest({ ...base, path: "/v1/me/memories?limit=5", method: "GET", fetch: fetchSpy });

    const [url, init] = fetchSpy.mock.calls[0] ?? [];
    expect(url instanceof URL ? url.href : "").toBe("http://127.0.0.1:8000/v1/me/memories?limit=5");
    expect(url instanceof URL ? url.href : "").not.toContain("tok-1");
    expect(init).toMatchObject({
      method: "GET",
      credentials: "omit",
      cache: "no-store",
      redirect: "error",
    });
    expect(init?.headers).toMatchObject({ Authorization: "Bearer tok-1" });
  });

  it("parses the body with the given parser", async () => {
    const value = await apiRequest({
      ...base,
      path: "/x",
      method: "GET",
      parse: (body) => (body as { n: number }).n,
      fetch: respond(jsonResponse(200, { n: 7 })),
    });

    expect(value).toBe(7);
  });

  it("resolves with nothing on 204", async () => {
    const call = apiRequest({
      ...base,
      path: "/x",
      method: "DELETE",
      fetch: respond(new Response(null, { status: 204 })),
    });

    await expect(call).resolves.toBeUndefined();
  });

  it("refuses a path that would move the token to another origin", async () => {
    const fetchSpy = vi.fn<typeof fetch>();
    await expect(
      apiRequest({ ...base, path: "//evil.example/x", method: "GET", fetch: fetchSpy }),
    ).rejects.toThrow(TypeError);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it.each([
    [401, { detail: "authentication_error" }, {}, "unauthorized"],
    [403, { detail: "authorization_error" }, {}, "forbidden"],
    [404, { detail: "memory_disabled" }, {}, "not_found"],
    [429, { detail: "rate_limited" }, { "Retry-After": "9" }, "rate_limited"],
    [500, { detail: "internal_server_error" }, {}, "server_error"],
    [503, { detail: "shutting_down" }, {}, "unavailable"],
  ])("classifies HTTP %i", async (status, body, headers, kind) => {
    const error = await failure(jsonResponse(status, body, headers));

    expect(error).toMatchObject({ kind, status });
  });

  it("keeps the machine code and the retry wait, and nothing else from the server", async () => {
    const error = await failure(
      jsonResponse(429, { detail: "rate_limited" }, { "Retry-After": "9" }),
    );

    expect(error).toMatchObject({ code: "rate_limited", retryAfterSeconds: 9 });
    const leaky = await failure(jsonResponse(500, { detail: "Traceback: password=hunter2" }));
    expect(leaky.code).toBeNull();
    expect(leaky.message).not.toContain("hunter2");
  });

  it("reports a network failure and a body of the wrong shape", async () => {
    await expect(
      apiRequest({
        ...base,
        path: "/x",
        method: "GET",
        fetch: () => Promise.reject(new TypeError("offline")),
      }),
    ).rejects.toMatchObject({ kind: "network" });
    await expect(
      apiRequest({
        ...base,
        path: "/x",
        method: "GET",
        parse: () => {
          throw new TypeError("shape");
        },
        fetch: respond(jsonResponse(200, {})),
      }),
    ).rejects.toMatchObject({ kind: "unexpected" });
  });
});
