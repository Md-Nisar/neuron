import { describe, expect, it } from "vitest";

import type { ApprovalRequired } from "@/lib/stream";

import { approvalStreamPath, MAX_ARGS_CHARS, viewAction } from "./approval";

function payload(approvalId: string, threadId = "t1"): ApprovalRequired {
  return {
    request_id: "r",
    thread_id: threadId,
    approval: {
      approval_id: approvalId,
      actions: [{ name: "remember", args: {} }],
      allowed_decisions: ["approve", "reject"],
    },
  };
}

describe("approvalStreamPath", () => {
  it("builds the approval stream endpoint from the two ids", () => {
    expect(approvalStreamPath(payload("a1", "0b1e-4c"))).toBe(
      "/v1/threads/0b1e-4c/approvals/a1/stream",
    );
  });

  it.each(["..", ".", "a/../b", "a/b", "a?b", "a#b", "a b", "%2e%2e", "", "x".repeat(129)])(
    "refuses the approval id %j instead of building a path from it",
    (id) => {
      expect(() => approvalStreamPath(payload(id))).toThrow(TypeError);
    },
  );

  it("refuses an unsafe thread id", () => {
    expect(() => approvalStreamPath(payload("a1", "../admin"))).toThrow(TypeError);
  });
});

describe("viewAction", () => {
  it("pretty-prints the arguments and marks short ones complete", () => {
    expect(viewAction({ name: "remember", args: { text: "tea" } })).toEqual({
      name: "remember",
      args: '{\n  "text": "tea"\n}',
      complete: true,
    });
  });

  it("marks arguments over the limit incomplete, at the exact boundary", () => {
    const overhead = JSON.stringify({ t: "" }, null, 2).length;
    const fits = viewAction({ name: "x", args: { t: "a".repeat(MAX_ARGS_CHARS - overhead) } });
    const over = viewAction({ name: "x", args: { t: "a".repeat(MAX_ARGS_CHARS - overhead + 1) } });

    expect(fits.complete).toBe(true);
    expect(over.complete).toBe(false);
    expect(over.args.length).toBe(MAX_ARGS_CHARS);
  });

  it("marks an over-long tool name incomplete", () => {
    expect(viewAction({ name: "n".repeat(65), args: {} }).complete).toBe(false);
  });
});
