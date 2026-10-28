import { describe, expect, it, vi } from "vitest";

import { parseRating, submitFeedback } from "./feedback";

const deps = (fetchMock: typeof fetch) => ({
  apiUrl: "http://127.0.0.1:8000",
  getAccessToken: () => "tok",
  onSessionEnded: vi.fn(),
  fetch: fetchMock,
});

describe("parseRating", () => {
  it("accepts a score with a known reason or none", () => {
    expect(parseRating({ run_id: "r", score: 1, reason: "helpful" })).toEqual({
      score: 1,
      reason: "helpful",
    });
    expect(parseRating({ run_id: "r", score: -1, reason: null })).toEqual({
      score: -1,
      reason: null,
    });
  });

  it.each([
    { score: 0, reason: null },
    { score: true, reason: null },
    { score: "1", reason: null },
    { score: 1, reason: "made up" },
    { score: 1, reason: 5 },
    { score: 1 },
    null,
    [],
  ])("refuses %j", (body) => {
    expect(() => parseRating(body)).toThrow();
  });
});

describe("submitFeedback", () => {
  it.each([
    ["..", "r1"],
    ["t1", ".."],
    ["a/b", "r1"],
    ["t1", "a/b"],
    ["", "r1"],
  ])("refuses the ids %j and %j before any request", async (thread, run) => {
    const fetchMock = vi.fn<typeof fetch>();

    await expect(
      submitFeedback(deps(fetchMock), thread, run, { score: 1, reason: null }),
    ).rejects.toThrow();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
