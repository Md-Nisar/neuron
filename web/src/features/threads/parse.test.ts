import { describe, expect, it } from "vitest";

import { parseRenamed, parseThreads } from "./parse";

const row = {
  thread_id: "00000000-0000-4000-8000-000000000001",
  title: "hi",
  updated_at: "2026-10-02T10:00:00Z",
  message_count: 2,
};

describe("parseThreads", () => {
  it("reads a page, with a title that may be null", () => {
    expect(parseThreads({ threads: [row, { ...row, title: null }], total: 2 })).toEqual({
      threads: [row, { ...row, title: null }],
      total: 2,
    });
  });

  it.each(["..", ".", "", "a/b", "../x", "a b", "x".repeat(129)])(
    "refuses the id %j, which would change the request path",
    (id) => {
      expect(() => parseThreads({ threads: [{ ...row, thread_id: id }], total: 1 })).toThrow();
    },
  );

  it.each([
    ["a numeric title", { ...row, title: 5 }],
    ["a missing title", { ...row, title: undefined }],
    ["a negative count", { ...row, message_count: -1 }],
    ["a missing date", { ...row, updated_at: undefined }],
  ])("refuses %s", (_name, bad) => {
    expect(() => parseThreads({ threads: [bad], total: 1 })).toThrow();
  });

  it("refuses a body that is not a page", () => {
    for (const body of [null, [], "x", { threads: {} }, { threads: [], total: "1" }]) {
      expect(() => parseThreads(body)).toThrow();
    }
  });
});

describe("parseRenamed", () => {
  it("returns the stored title", () => {
    expect(parseRenamed({ thread_id: "t", title: "New" })).toBe("New");
    expect(() => parseRenamed({ thread_id: "t" })).toThrow();
  });
});
