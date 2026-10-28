import { describe, expect, it, vi } from "vitest";

import { parseHistory } from "./history";
import { getHistory, getPendingApproval } from "./historyApi";

const deps = (fetchMock: typeof fetch) => ({
  apiUrl: "http://127.0.0.1:8000",
  getAccessToken: () => "tok",
  onSessionEnded: vi.fn(),
  fetch: fetchMock,
});

describe("history requests", () => {
  it.each(["..", ".", "a/b", "../x", ""])(
    "refuse the thread id %j before any request",
    async (id) => {
      const fetchMock = vi.fn<typeof fetch>();

      await expect(getHistory(deps(fetchMock), id, 0)).rejects.toThrow();
      await expect(getPendingApproval(deps(fetchMock), id)).rejects.toThrow();
      expect(fetchMock).not.toHaveBeenCalled();
    },
  );
});

describe("run IDs in history", () => {
  const page = (run_id: unknown) => ({
    messages: [{ role: "assistant", content: "a", tool_calls: [], run_id }],
    total: 1,
  });

  it("are kept when safe and absent otherwise", () => {
    expect(parseHistory(page("5a7f2c10-1b2c-4d3e-8f90-a1b2c3d4e5f6")).messages[0]?.runId).toBe(
      "5a7f2c10-1b2c-4d3e-8f90-a1b2c3d4e5f6",
    );
    expect(parseHistory(page(null)).messages[0]?.runId).toBeNull();
    expect(parseHistory(page(undefined)).messages[0]?.runId).toBeNull();
  });

  it.each(["../x", "a/b", "", 7, {}])("refuse the run id %j", (run) => {
    expect(() => parseHistory(page(run))).toThrow();
  });
});
