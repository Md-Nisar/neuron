import { vi } from "vitest";

import { jsonResponse } from "./sse";

export interface FakeMemory {
  id: string;
  text: string;
  created_at: string;
}
export interface FakeMessage {
  role: "user" | "assistant";
  content: string;
}
export interface FakeThread {
  thread_id: string;
  created_at: string;
  updated_at: string;
  messages: FakeMessage[];
}

export interface FakeData {
  memories: FakeMemory[];
  threads: FakeThread[];
  /** Responses larger than this many messages-times-threads are refused with 413. */
  maxItemsPerPage?: number;
  memoryEnabled?: boolean;
  eraseSkipsBusy?: number;
}

export const memory = (n: number, text = `memory ${String(n)}`): FakeMemory => ({
  id: `mem-${String(n)}`,
  text,
  created_at: "2026-10-01T10:00:00Z",
});

export const thread = (n: number, messages: number): FakeThread => ({
  thread_id: `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`,
  created_at: "2026-10-01T10:00:00Z",
  updated_at: "2026-10-02T10:00:00Z",
  messages: Array.from({ length: messages }, (_, i) => ({
    role: i % 2 === 0 ? "user" : "assistant",
    content: `t${String(n)} message ${String(i)}`,
  })),
});

/** A fetch that answers like the real API's `/v1/me/*` routes, including their paging rules. */
export function fakeApi(data: FakeData) {
  const calls: { method: string; url: URL; headers: HeadersInit | undefined }[] = [];
  const handler: typeof fetch = (input, init) => {
    const url = new URL(
      input instanceof URL ? input.href : typeof input === "string" ? input : input.url,
    );
    const method = init?.method ?? "GET";
    calls.push({ method, url, headers: init?.headers });
    const q = url.searchParams;
    const int = (name: string, fallback: number) => Number(q.get(name) ?? fallback);

    if (url.pathname === "/v1/me/memories" && method === "GET") {
      if (data.memoryEnabled === false)
        return Promise.resolve(jsonResponse(404, { detail: "memory_disabled" }));
      const offset = int("offset", 0);
      const limit = int("limit", 50);
      return Promise.resolve(
        jsonResponse(200, {
          memories: data.memories.slice(offset, offset + limit),
          total: data.memories.length,
          limit,
          offset,
        }),
      );
    }
    if (url.pathname.startsWith("/v1/me/memories/") && method === "DELETE") {
      const id = decodeURIComponent(url.pathname.slice("/v1/me/memories/".length));
      const found = data.memories.some((m) => m.id === id);
      data.memories = data.memories.filter((m) => m.id !== id);
      return Promise.resolve(
        found
          ? new Response(null, { status: 204 })
          : jsonResponse(404, { detail: "memory_not_found" }),
      );
    }
    if (url.pathname === "/v1/me/export" && method === "GET") {
      const limit = int("limit", 5);
      const offset = int("offset", 0);
      const ml = int("message_limit", 20);
      const mo = int("message_offset", 0);
      if (data.maxItemsPerPage !== undefined && limit * ml > data.maxItemsPerPage) {
        return Promise.resolve(jsonResponse(413, { detail: "export_too_large" }));
      }
      const page = data.threads.slice(offset, offset + limit);
      return Promise.resolve(
        jsonResponse(200, {
          threads: page.map((t) => ({
            thread_id: t.thread_id,
            created_at: t.created_at,
            updated_at: t.updated_at,
            message_total: t.messages.length,
            messages: t.messages.slice(mo, mo + ml),
          })),
          total_threads: data.threads.length,
          limit,
          offset,
          message_limit: ml,
          message_offset: mo,
          has_more_messages: page.some((t) => mo + ml < t.messages.length),
          memories: offset === 0 ? data.memories : [],
        }),
      );
    }
    if (url.pathname === "/v1/me/threads" && method === "DELETE") {
      const skipped = data.eraseSkipsBusy ?? 0;
      const erased = data.threads.length - skipped;
      const erasedMemories = data.memories.length;
      data.threads = data.threads.slice(erased);
      data.memories = [];
      return Promise.resolve(
        jsonResponse(200, {
          erased_count: erased,
          skipped_busy_count: skipped,
          erased_memory_count: erasedMemories,
          complete: skipped === 0,
        }),
      );
    }
    return Promise.resolve(new Response("not found", { status: 404 }));
  };
  return { fetch: vi.fn(handler), calls, data };
}
