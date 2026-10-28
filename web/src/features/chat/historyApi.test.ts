import { describe, expect, it, vi } from "vitest";

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
