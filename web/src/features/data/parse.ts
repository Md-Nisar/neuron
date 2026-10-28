import { SAFE_ID } from "@/lib/stream";

/** Shape checks for the data-rights responses. A wrong shape throws; nothing is half-trusted. */

export interface Memory {
  id: string;
  text: string;
  created_at: string;
}

export interface MemoriesPage {
  memories: Memory[];
  total: number;
}

export interface ExportedMessage {
  role: string;
  content: string;
  tool_calls?: unknown[];
}

export interface ExportedThread {
  thread_id: string;
  created_at: string;
  updated_at: string;
  message_total: number;
  messages: ExportedMessage[];
}

export interface ExportPage {
  threads: ExportedThread[];
  total_threads: number;
  has_more_messages: boolean;
  memories: Memory[];
}

export interface Erasure {
  erased_count: number;
  skipped_busy_count: number;
  erased_memory_count: number;
  complete: boolean;
}

function record(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value))
    throw new TypeError("shape");
  return value as Record<string, unknown>;
}

function str(source: Record<string, unknown>, key: string): string {
  const value = source[key];
  if (typeof value !== "string") throw new TypeError("shape");
  return value;
}

function count(source: Record<string, unknown>, key: string): number {
  const value = source[key];
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0)
    throw new TypeError("shape");
  return value;
}

function list(source: Record<string, unknown>, key: string): unknown[] {
  const value = source[key];
  if (!Array.isArray(value)) throw new TypeError("shape");
  return value as unknown[];
}

function parseMemory(value: unknown): Memory {
  const item = record(value);
  const id = str(item, "id");
  // The id becomes a URL path segment when deleting.
  if (!SAFE_ID.test(id)) throw new TypeError("shape");
  return { id, text: str(item, "text"), created_at: str(item, "created_at") };
}

export function parseMemories(body: unknown): MemoriesPage {
  const page = record(body);
  return { memories: list(page, "memories").map(parseMemory), total: count(page, "total") };
}

function parseThread(value: unknown): ExportedThread {
  const thread = record(value);
  return {
    thread_id: str(thread, "thread_id"),
    created_at: str(thread, "created_at"),
    updated_at: str(thread, "updated_at"),
    message_total: count(thread, "message_total"),
    messages: list(thread, "messages").map((message): ExportedMessage => {
      const item = record(message);
      const calls = item["tool_calls"];
      return {
        role: str(item, "role"),
        content: str(item, "content"),
        ...(Array.isArray(calls) ? { tool_calls: calls as unknown[] } : {}),
      };
    }),
  };
}

export function parseExportPage(body: unknown): ExportPage {
  const page = record(body);
  const more = page["has_more_messages"];
  if (typeof more !== "boolean") throw new TypeError("shape");
  const memories = page["memories"];
  return {
    threads: list(page, "threads").map(parseThread),
    total_threads: count(page, "total_threads"),
    has_more_messages: more,
    memories: Array.isArray(memories) ? (memories as unknown[]).map(parseMemory) : [],
  };
}

export function parseErasure(body: unknown): Erasure {
  const result = record(body);
  const complete = result["complete"];
  if (typeof complete !== "boolean") throw new TypeError("shape");
  return {
    erased_count: count(result, "erased_count"),
    skipped_busy_count: count(result, "skipped_busy_count"),
    erased_memory_count: count(result, "erased_memory_count"),
    complete,
  };
}
