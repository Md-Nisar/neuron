import { count, list, record, str } from "@/features/data/parse";
import { SAFE_ID } from "@/lib/stream";

/** Shape checks for the conversation routes. A wrong shape throws; nothing is half-trusted. */

export interface ThreadSummary {
  thread_id: string;
  /** Untrusted: derived from what the user typed, or set by them. Shown as text only. */
  title: string | null;
  updated_at: string;
  message_count: number;
}

export interface ThreadsPage {
  threads: ThreadSummary[];
  total: number;
}

function parseThread(value: unknown): ThreadSummary {
  const item = record(value);
  const id = str(item, "thread_id");
  // The id becomes a URL path segment when renaming or deleting.
  if (!SAFE_ID.test(id)) throw new TypeError("shape");
  const title = item["title"];
  if (title !== null && typeof title !== "string") throw new TypeError("shape");
  return {
    thread_id: id,
    title: title ?? null,
    updated_at: str(item, "updated_at"),
    message_count: count(item, "message_count"),
  };
}

export function parseThreads(body: unknown): ThreadsPage {
  const page = record(body);
  return { threads: list(page, "threads").map(parseThread), total: count(page, "total") };
}

/** The title the server stored, which may differ from what was sent (whitespace is collapsed). */
export function parseRenamed(body: unknown): string {
  return str(record(body), "title");
}
