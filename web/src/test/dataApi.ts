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
  tool_calls?: { name: string; summary: string; status: string }[];
  run_id?: string | null;
}
export interface FakeApproval {
  approval_id: string;
  actions: { name: string; args: Record<string, unknown> }[];
  /** Answer with another thread's id, as a hostile server might. */
  thread_id?: string;
}
export interface FakeThread {
  thread_id: string;
  created_at: string;
  updated_at: string;
  messages: FakeMessage[];
  title?: string | null;
  /** Ratings by run id: the first one stands, like the server's. */
  ratings?: Record<string, { score: number; reason: string | null }>;
  /** The approval a paused thread waits on. */
  pending?: FakeApproval | undefined;
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
    if (url.pathname === "/v1/me/threads" && method === "GET") {
      const offset = int("offset", 0);
      const limit = int("limit", 50);
      return Promise.resolve(
        jsonResponse(200, {
          threads: data.threads.slice(offset, offset + limit).map((t) => ({
            thread_id: t.thread_id,
            title: t.title ?? null,
            created_at: t.created_at,
            updated_at: t.updated_at,
            message_count: t.messages.length,
          })),
          total: data.threads.length,
          limit,
          offset,
        }),
      );
    }
    const sub = /^\/v1\/threads\/([^/]+)\/(messages|approval)$/.exec(url.pathname);
    if (sub !== null && method === "GET") {
      const found = data.threads.find((t) => t.thread_id === decodeURIComponent(sub[1] ?? ""));
      if (found === undefined)
        return Promise.resolve(jsonResponse(404, { detail: "thread_not_found" }));
      if (sub[2] === "approval") {
        const { pending } = found;
        if (pending === undefined)
          return Promise.resolve(jsonResponse(404, { detail: "approval_not_found" }));
        return Promise.resolve(
          jsonResponse(200, {
            status: "approval_required",
            request_id: "req-1",
            thread_id: pending.thread_id ?? found.thread_id,
            approval: {
              approval_id: pending.approval_id,
              actions: pending.actions,
              allowed_decisions: ["approve", "reject"],
            },
          }),
        );
      }
      const offset = int("offset", 0);
      const limit = Math.min(int("limit", 50), 100);
      return Promise.resolve(
        jsonResponse(200, {
          thread_id: found.thread_id,
          messages: found.messages.slice(offset, offset + limit),
          total: found.messages.length,
          limit,
          offset,
        }),
      );
    }
    const rate = /^\/v1\/threads\/([^/]+)\/runs\/([^/]+)\/feedback$/.exec(url.pathname);
    if (rate !== null && method === "POST") {
      const found = data.threads.find((t) => t.thread_id === decodeURIComponent(rate[1] ?? ""));
      if (found === undefined)
        return Promise.resolve(jsonResponse(404, { detail: "thread_not_found" }));
      const sent = JSON.parse(typeof init?.body === "string" ? init.body : "{}") as {
        score?: number;
        reason?: string;
      };
      const runId = decodeURIComponent(rate[2] ?? "");
      found.ratings ??= {};
      found.ratings[runId] ??= { score: sent.score ?? 0, reason: sent.reason ?? null };
      return Promise.resolve(jsonResponse(200, { run_id: runId, ...found.ratings[runId] }));
    }
    const single = /^\/v1\/threads\/([^/]+)$/.exec(url.pathname);
    if (single !== null && (method === "PATCH" || method === "DELETE")) {
      const found = data.threads.find((t) => t.thread_id === decodeURIComponent(single[1] ?? ""));
      if (found === undefined)
        return Promise.resolve(jsonResponse(404, { detail: "thread_not_found" }));
      if (method === "DELETE") {
        data.threads = data.threads.filter((t) => t !== found);
        return Promise.resolve(new Response(null, { status: 204 }));
      }
      const sent = (
        JSON.parse(typeof init?.body === "string" ? init.body : "{}") as { title?: unknown }
      ).title;
      const title = typeof sent === "string" ? sent.split(/\s+/).filter(Boolean).join(" ") : "";
      if (title === "" || title.length > 80) {
        return Promise.resolve(jsonResponse(422, { detail: "validation_error" }));
      }
      found.title = title;
      return Promise.resolve(jsonResponse(200, { thread_id: found.thread_id, title }));
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
