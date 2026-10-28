import { describe, expect, it, vi } from "vitest";

import { fakeApi, memory, thread, type FakeData } from "@/test/dataApi";
import { jsonResponse } from "@/test/sse";

import { ApiError } from "@/lib/request";

import type { DataDeps } from "./api";
import { buildExport, downloadText, ExportError, exportFilename } from "./exportData";

function deps(
  fetchImpl: typeof fetch,
  token: string | null = "tok-1",
  onSessionEnded: () => void = vi.fn(),
): DataDeps {
  return {
    apiUrl: "http://127.0.0.1:8000",
    getAccessToken: () => token,
    onSessionEnded,
    fetch: fetchImpl,
  };
}

const dataset = (): FakeData => ({
  memories: [memory(1), memory(2)],
  threads: [0, 1, 25, 45, 2, 3, 60].map((count, index) => thread(index + 1, count)),
});

describe("buildExport", () => {
  it("returns every thread, every message in order, and the memories once", async () => {
    const api = fakeApi(dataset());
    const exported = JSON.parse(await buildExport(deps(api.fetch))) as {
      exported_at: string;
      threads: { thread_id: string; message_total: number; messages: { content: string }[] }[];
      memories: unknown[];
    };

    const expected = dataset();
    expect(exported.threads.map((t) => t.thread_id)).toEqual(
      expected.threads.map((t) => t.thread_id),
    );
    expect(exported.threads.map((t) => t.messages.map((m) => m.content))).toEqual(
      expected.threads.map((t) => t.messages.map((m) => m.content)),
    );
    expect(exported.threads.map((t) => t.message_total)).toEqual([0, 1, 25, 45, 2, 3, 60]);
    expect(exported.memories).toEqual(expected.memories);
    expect(Number.isNaN(Date.parse(exported.exported_at))).toBe(false);
  });

  it("pages threads and messages independently", async () => {
    const api = fakeApi(dataset());
    await buildExport(deps(api.fetch));
    const pages = api.calls.map((call) => [
      call.url.searchParams.get("offset"),
      call.url.searchParams.get("message_offset"),
    ]);

    // Threads 1-5 need message offsets 0, 20, 40 (the 45-message thread); threads 6-7 need 0, 20, 40 (the 60-message one).
    expect(pages).toEqual([
      ["0", "0"],
      ["0", "20"],
      ["0", "40"],
      ["5", "0"],
      ["5", "20"],
      ["5", "40"],
    ]);
  });

  it("works for an account with no conversations", async () => {
    const api = fakeApi({ memories: [memory(1)], threads: [] });
    const exported = JSON.parse(await buildExport(deps(api.fetch))) as {
      threads: unknown[];
      memories: unknown[];
    };

    expect(exported.threads).toEqual([]);
    expect(exported.memories).toHaveLength(1);
    expect(api.calls).toHaveLength(1);
  });

  it("halves the page sizes and retries when the API says a page is too large", async () => {
    const api = fakeApi({ ...dataset(), maxItemsPerPage: 20 });
    const exported = JSON.parse(await buildExport(deps(api.fetch))) as {
      threads: { messages: unknown[] }[];
    };

    expect(exported.threads.map((t) => t.messages.length)).toEqual([0, 1, 25, 45, 2, 3, 60]);
    expect(api.calls.length).toBeGreaterThan(6);
  });

  it("gives up when even the smallest page is too large", async () => {
    const api = fakeApi({ ...dataset(), maxItemsPerPage: 0 });

    await expect(buildExport(deps(api.fetch))).rejects.toMatchObject({ status: 413 });
  });

  it("refuses to hand over a partial file when a thread is missing messages", async () => {
    const lying: typeof fetch = () =>
      Promise.resolve(
        jsonResponse(200, {
          threads: [
            {
              thread_id: "t1",
              created_at: "a",
              updated_at: "b",
              message_total: 3,
              messages: [{ role: "user", content: "only one" }],
            },
          ],
          total_threads: 1,
          has_more_messages: false,
          memories: [],
        }),
      );

    await expect(buildExport(deps(lying))).rejects.toMatchObject({ reason: "incomplete" });
  });

  it("refuses an export that grows past the size cap", async () => {
    const api = fakeApi(dataset());

    await expect(buildExport(deps(api.fetch), undefined, 100)).rejects.toMatchObject({
      reason: "too_large",
    });
    await expect(buildExport(deps(api.fetch), undefined, 100)).rejects.toBeInstanceOf(ExportError);
  });

  it("does not guess when a page fails: the whole export fails", async () => {
    const api = fakeApi(dataset());
    let calls = 0;
    const flaky: typeof fetch = (input, init) =>
      ++calls === 3 ? Promise.resolve(jsonResponse(500, { detail: "x" })) : api.fetch(input, init);

    await expect(buildExport(deps(flaky))).rejects.toMatchObject({ kind: "server_error" });
  });

  it("ends the session when there is no token, without calling the API", async () => {
    const api = fakeApi(dataset());
    const ended = vi.fn();

    await expect(buildExport(deps(api.fetch, null, ended))).rejects.toBeInstanceOf(ApiError);
    expect(ended).toHaveBeenCalledOnce();
    expect(api.calls).toHaveLength(0);
  });
});

describe("downloadText", () => {
  it("gives the browser a file, clicks it once, and revokes the URL straight after", async () => {
    const created: Blob[] = [];
    const revoked: string[] = [];
    const urls = {
      createObjectURL: (blob: Blob) => {
        created.push(blob);
        return "blob:fake-1";
      },
      revokeObjectURL: (url: string) => {
        revoked.push(url);
      },
    };
    const clicks: { download: string; href: string }[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      clicks.push({ download: this.download, href: this.getAttribute("href") ?? "" });
    });
    vi.useFakeTimers();
    downloadText('{"a":1}', "neuron-export-2026-10-28.json", document, urls);

    expect(clicks).toEqual([{ download: "neuron-export-2026-10-28.json", href: "blob:fake-1" }]);
    expect(await created[0]?.text()).toBe('{"a":1}');
    expect(created[0]?.type).toBe("application/json");
    expect(document.querySelector("a[download]")).toBeNull();
    expect(revoked).toEqual([]);
    vi.runAllTimers();
    expect(revoked).toEqual(["blob:fake-1"]);
    vi.useRealTimers();
    vi.restoreAllMocks();
  });
});

describe("exportFilename", () => {
  it("is dated and has no user data in it", () => {
    expect(exportFilename(new Date("2026-10-28T23:59:00Z"))).toBe("neuron-export-2026-10-28.json");
  });
});
