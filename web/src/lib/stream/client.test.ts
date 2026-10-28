import { describe, expect, it, vi } from "vitest";

import { collect, controlledStream, frame, jsonResponse, sseResponse, streamOf } from "@/test/sse";

import { parseRetryAfter, StreamStartError, streamRun } from "./client";
import contract from "./contract.json";
import type { StreamEvent } from "./events";

const BASE = "http://127.0.0.1:8000";
const started = { request_id: "r1", thread_id: "t1", run_id: "u1" };
const answer = { ...contract.payloads.final, run_id: "u1" };
const approval = contract.payloads.approval_required;

function run(
  fetchImpl: typeof fetch,
  extra: { signal?: AbortSignal; maxEventChars?: number } = {},
) {
  return streamRun({
    baseUrl: BASE,
    path: "/v1/agent/stream",
    token: "tok-123",
    body: { message: "hi" },
    fetch: fetchImpl,
    ...extra,
  });
}

const respond =
  (response: Response): typeof fetch =>
  () =>
    Promise.resolve(response);
const types = (events: StreamEvent[]): string[] => events.map((event) => event.type);

describe("contract fixture", () => {
  it("lists exactly the events the client implements", () => {
    expect(contract.events).toEqual([
      "run_started",
      "token",
      "tool_call",
      "final",
      "approval_required",
      "error",
      "done",
    ]);
    expect(contract.protocol_version).toBe("1");
  });
});

describe("streamRun: events", () => {
  it("yields all seven events in order, validated", async () => {
    const wire = [
      frame("run_started", started),
      frame("token", { text: "5" }),
      frame("tool_call", { name: "calculator" }),
      frame("final", answer),
      frame("approval_required", approval),
      frame("error", { code: "run_timeout", retryable: true }),
      frame("done", {}),
    ];
    const events = await collect(run(respond(sseResponse(streamOf(wire)))));

    expect(types(events)).toEqual([
      "run_started",
      "token",
      "tool_call",
      "final",
      "approval_required",
      "error",
      "done",
    ]);
    expect(events[3]).toMatchObject({ type: "final", data: { answer: "57", run_id: "u1" } });
    expect(events[4]).toMatchObject({
      type: "approval_required",
      data: { approval: { approval_id: "a1" } },
    });
  });

  it("accepts a run_started and final without run_id (older servers)", async () => {
    const withoutRunId = (value: object): object =>
      Object.fromEntries(Object.entries(value).filter(([key]) => key !== "run_id"));
    const startedNoId = withoutRunId(started);
    const answerNoId = withoutRunId(answer);
    const wire = [frame("run_started", startedNoId), frame("final", answerNoId), frame("done", {})];
    const events = await collect(run(respond(sseResponse(streamOf(wire)))));

    expect(types(events)).toEqual(["run_started", "final", "done"]);
  });

  it("ignores heartbeat comments and unknown events, and stops reading after done", async () => {
    let cancelled = false;
    const wire = [
      ": ping\r\n\r\n",
      frame("future_event", { anything: true }),
      frame("token", { text: "a" }),
      frame("done", {}),
      frame("token", { text: "after done" }),
    ];
    const events = await collect(
      run(respond(sseResponse(streamOf(wire, "close", () => (cancelled = true))))),
    );

    expect(types(events)).toEqual(["token", "done"]);
    expect(cancelled).toBe(true);
  });

  it("passes a server error through and then done, adding nothing", async () => {
    const wire = [
      frame("run_started", started),
      frame("token", { text: "par" }),
      frame("error", { code: "model_unavailable", retryable: true }),
      frame("done", {}),
    ];
    const events = await collect(run(respond(sseResponse(streamOf(wire)))));

    expect(types(events)).toEqual(["run_started", "token", "error", "done"]);
    expect(events[2]).toEqual({
      type: "error",
      data: { code: "model_unavailable", retryable: true },
    });
  });

  it("replaces an unsafe error code from the server with a fixed one", async () => {
    const wire = [frame("error", { code: "<img src=x onerror=alert(1)>", retryable: false })];
    const events = await collect(run(respond(sseResponse(streamOf([...wire, frame("done", {})])))));

    expect(events[0]).toEqual({ type: "error", data: { code: "unknown_error", retryable: false } });
  });
});

describe("streamRun: a stream that breaks", () => {
  it("surfaces error then done when the connection drops mid-stream", async () => {
    const stream = streamOf([frame("token", { text: "par" })], new TypeError("network error"));
    const events = await collect(run(respond(sseResponse(stream))));

    expect(events).toEqual([
      { type: "token", data: { text: "par" } },
      { type: "error", data: { code: "stream_interrupted", retryable: true } },
      { type: "done", data: {} },
    ]);
  });

  it("surfaces error then done when the stream ends without done", async () => {
    const events = await collect(
      run(respond(sseResponse(streamOf([frame("token", { text: "a" })])))),
    );

    expect(types(events)).toEqual(["token", "error", "done"]);
  });

  it("adds only done when the server sent error but the stream then ended", async () => {
    const wire = [frame("error", { code: "internal_server_error", retryable: false })];
    const events = await collect(run(respond(sseResponse(streamOf(wire)))));

    expect(types(events)).toEqual(["error", "done"]);
  });

  it.each([
    ["malformed JSON", "event: token\r\ndata: {not json\r\n\r\n"],
    ["a wrong payload shape", frame("token", { text: 42 })],
    ["a non-object payload", frame("final", ["x"])],
    ["a final missing its answer", frame("final", { ...answer, answer: undefined })],
    [
      "an approval with no actions",
      frame("approval_required", { ...approval, approval: { ...approval.approval, actions: [] } }),
    ],
  ])("reports a protocol error, not partial data, for %s", async (_name, bad) => {
    const events = await collect(
      run(respond(sseResponse(streamOf([frame("token", { text: "ok" }), bad])))),
    );

    expect(events.map((event) => event.type)).toEqual(["token", "error", "done"]);
    expect(events[1]).toEqual({
      type: "error",
      data: { code: "protocol_error", retryable: false },
    });
  });

  it("refuses an oversized event instead of buffering it", async () => {
    const huge = frame("token", { text: "x".repeat(5000) });
    const events = await collect(
      run(respond(sseResponse(streamOf([huge]))), { maxEventChars: 1000 }),
    );

    expect(events).toEqual([
      { type: "error", data: { code: "event_too_large", retryable: false } },
      { type: "done", data: {} },
    ]);
  });
});

describe("streamRun: abort", () => {
  it("ends quietly after abort, with no error and no done, and cancels the stream", async () => {
    let cancelled = false;
    const { stream, push } = controlledStream(() => (cancelled = true));
    const controller = new AbortController();
    const seen: string[] = [];
    const finished = (async () => {
      for await (const event of run(respond(sseResponse(stream)), { signal: controller.signal })) {
        seen.push(event.type);
        if (event.type === "token") controller.abort();
      }
    })();
    push(frame("run_started", started));
    push(frame("token", { text: "a" }));
    await finished;

    expect(seen).toEqual(["run_started", "token"]);
    expect(cancelled).toBe(true);
  });

  it("ends quietly when aborted before the response arrives", async () => {
    const controller = new AbortController();
    const rejecting: typeof fetch = () => {
      controller.abort();
      return Promise.reject(new DOMException("aborted", "AbortError"));
    };

    expect(await collect(run(rejecting, { signal: controller.signal }))).toEqual([]);
  });
});

describe("streamRun: failures before the first byte", () => {
  const failure = async (response: Response): Promise<StreamStartError> => {
    try {
      await collect(run(respond(response)));
    } catch (error) {
      if (error instanceof StreamStartError) return error;
      throw error;
    }
    throw new Error("expected a StreamStartError");
  };

  it("401 means sign in again", async () => {
    const error = await failure(jsonResponse(401, { detail: "authentication_error" }));
    expect(error).toMatchObject({
      kind: "unauthorized",
      status: 401,
      code: "authentication_error",
    });
  });

  it("403 and 404 are distinct", async () => {
    expect((await failure(jsonResponse(403, { detail: "authorization_error" }))).kind).toBe(
      "forbidden",
    );
    expect((await failure(jsonResponse(404, { detail: "thread_not_found" }))).kind).toBe(
      "not_found",
    );
  });

  it("409 distinguishes a busy thread from a pending approval", async () => {
    expect((await failure(jsonResponse(409, { detail: "thread_busy" }))).kind).toBe("thread_busy");
    expect((await failure(jsonResponse(409, { detail: "approval_pending" }))).kind).toBe(
      "approval_pending",
    );
    expect((await failure(jsonResponse(409, { detail: "something_else" }))).kind).toBe("conflict");
  });

  it("429 carries Retry-After in seconds", async () => {
    const error = await failure(
      jsonResponse(429, { detail: "rate_limited" }, { "Retry-After": "7" }),
    );
    expect(error).toMatchObject({ kind: "rate_limited", status: 429, retryAfterSeconds: 7 });
  });

  it("503, other 5xx and validation errors map to their own kinds", async () => {
    expect(
      (await failure(jsonResponse(503, { detail: "shutting_down" }, { "Retry-After": "1" }))).kind,
    ).toBe("unavailable");
    expect((await failure(jsonResponse(500, { detail: "internal_server_error" }))).kind).toBe(
      "server_error",
    );
    expect((await failure(jsonResponse(422, { detail: [{ msg: "field required" }] }))).kind).toBe(
      "invalid_request",
    );
  });

  it("never surfaces free-form server text as the error code", async () => {
    const error = await failure(jsonResponse(500, { detail: "Traceback: secret at /srv/app.py" }));
    expect(error.code).toBeNull();
    expect(error.message).not.toContain("secret");
  });

  it("a network failure is its own kind", async () => {
    const down: typeof fetch = () => Promise.reject(new TypeError("Failed to fetch"));
    await expect(collect(run(down))).rejects.toMatchObject({ kind: "network" });
  });

  it("a 200 that is not an event stream is unexpected (a proxy's HTML page)", async () => {
    const html = new Response("<html>login</html>", {
      status: 200,
      headers: { "Content-Type": "text/html" },
    });
    await expect(collect(run(respond(html)))).rejects.toMatchObject({ kind: "unexpected" });
  });
});

describe("parseRetryAfter", () => {
  const now = Date.parse("2026-10-28T12:00:00Z");

  it("reads delta-seconds and HTTP dates, and clamps absurd values", () => {
    expect(parseRetryAfter("12", now)).toBe(12);
    expect(parseRetryAfter("Wed, 28 Oct 2026 12:00:30 GMT", now)).toBe(30);
    expect(parseRetryAfter("Wed, 28 Oct 2026 11:00:00 GMT", now)).toBe(0);
    expect(parseRetryAfter("999999999", now)).toBe(3600);
  });

  it("returns null for a missing or unreadable header", () => {
    expect(parseRetryAfter(null, now)).toBeNull();
    expect(parseRetryAfter("soon", now)).toBeNull();
    expect(parseRetryAfter("-5", now)).toBeNull();
  });
});

describe("streamRun: the request", () => {
  it("POSTs JSON with the bearer token in a header only, and no cookies", async () => {
    const fetchSpy = vi.fn<typeof fetch>(() =>
      Promise.resolve(sseResponse(streamOf([frame("done", {})]))),
    );
    await collect(run(fetchSpy));

    const [url, init] = fetchSpy.mock.calls[0] ?? [];
    expect(url).toBeInstanceOf(URL);
    const href = url instanceof URL ? url.href : "";
    expect(href).toBe(`${BASE}/v1/agent/stream`);
    expect(href).not.toContain("tok-123");
    expect(init).toMatchObject({
      method: "POST",
      body: JSON.stringify({ message: "hi" }),
      credentials: "omit",
      redirect: "error",
      cache: "no-store",
    });
    expect(init?.headers).toMatchObject({
      Authorization: "Bearer tok-123",
      Accept: "text/event-stream",
      "Content-Type": "application/json",
    });
  });

  it.each(["//evil.example/steal", "https://evil.example/v1/agent/stream", "\\\\evil.example\\x"])(
    "never sends the token to another origin (path %s)",
    async (path) => {
      const fetchSpy = vi.fn<typeof fetch>();
      const call = collect(streamRun({ baseUrl: BASE, path, token: "tok-123", fetch: fetchSpy }));

      await expect(call).rejects.toThrow(TypeError);
      expect(fetchSpy).not.toHaveBeenCalled();
    },
  );

  it("refuses a base URL that is not http(s)", async () => {
    const call = collect(
      streamRun({ baseUrl: "file:///etc", path: "/x", token: "t", fetch: vi.fn() }),
    );
    await expect(call).rejects.toThrow(TypeError);
  });
});

describe("approval ids from the server are path-safe", () => {
  const wire = (approvalId: string, threadId = "t1") =>
    frame("approval_required", {
      ...approval,
      thread_id: threadId,
      approval: { ...approval.approval, approval_id: approvalId },
    });

  it.each(["..", ".", "a/b", "a b", "a?b=1", "a#b", "%2e%2e", "", "x".repeat(129), "../x", "a\n"])(
    "reports a protocol error for the approval id %j",
    async (id) => {
      const events = await collect(run(respond(sseResponse(streamOf([wire(id)])))));

      expect(events[0]).toEqual({
        type: "error",
        data: { code: "protocol_error", retryable: false },
      });
    },
  );

  it("reports a protocol error for an unsafe thread id", async () => {
    const events = await collect(run(respond(sseResponse(streamOf([wire("a1", "../t")])))));

    expect(events[0]).toMatchObject({ type: "error", data: { code: "protocol_error" } });
  });

  it.each(["a1", "approval:7f3a.9-b_c", "..a", "a.."])("accepts the approval id %j", async (id) => {
    const events = await collect(
      run(respond(sseResponse(streamOf([wire(id), frame("done", {})])))),
    );

    expect(events[0]).toMatchObject({ type: "approval_required" });
  });
});
