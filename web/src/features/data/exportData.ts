import { ApiError } from "@/lib/request";

import { exportPage, type DataDeps } from "./api";
import type { ExportedMessage, ExportedThread, Memory } from "./parse";

/** The export is assembled in the browser; past this size it is refused rather than held. */
export const MAX_EXPORT_CHARS = 64 * 1024 * 1024;
const MAX_REQUESTS = 10_000;

export class ExportError extends Error {
  constructor(readonly reason: "too_large" | "incomplete") {
    super(`export failed: ${reason}`);
    this.name = "ExportError";
  }
}

/**
 * Fetch all of the caller's threads, messages and memories and return them as one JSON text.
 *
 * The API pages threads and, independently, the messages inside them, and refuses a page over
 * its size limit (413); this halves the page sizes and retries. The result is checked for
 * completeness (every thread has all its `message_total` messages) so a partial file is never
 * offered as the user's data. Nothing is stored: the text is returned to the caller, which
 * hands it to the browser and drops it.
 */
export async function buildExport(
  deps: DataDeps,
  signal?: AbortSignal,
  maxChars: number = MAX_EXPORT_CHARS,
): Promise<string> {
  let threadLimit = 5;
  let messageLimit = 20;
  let requests = 0;
  let size = 0;
  let memories: Memory[] = [];
  const threads = new Map<string, ExportedThread>();
  const messages = new Map<string, (ExportedMessage | undefined)[]>();

  let offset = 0;
  let totalThreads = 1;
  while (offset < totalThreads) {
    let messageOffset = 0;
    for (;;) {
      if (++requests > MAX_REQUESTS) throw new ExportError("too_large");
      let page;
      try {
        page = await exportPage(
          deps,
          { limit: threadLimit, offset, messageLimit, messageOffset },
          signal,
        );
      } catch (error) {
        const tooBig = error instanceof ApiError && error.status === 413;
        if (tooBig && (threadLimit > 1 || messageLimit > 1)) {
          threadLimit = Math.max(1, Math.floor(threadLimit / 2));
          messageLimit = Math.max(1, Math.floor(messageLimit / 2));
          continue;
        }
        throw error;
      }
      totalThreads = page.total_threads;
      if (offset === 0 && messageOffset === 0) memories = page.memories;
      for (const thread of page.threads) {
        if (!threads.has(thread.thread_id)) {
          threads.set(thread.thread_id, { ...thread, messages: [] });
          messages.set(thread.thread_id, []);
        }
        const slots = messages.get(thread.thread_id);
        thread.messages.forEach((message, index) => {
          if (slots !== undefined) slots[messageOffset + index] = message;
          size += message.content.length;
        });
      }
      if (size > maxChars) throw new ExportError("too_large");
      if (!page.has_more_messages) break;
      messageOffset += messageLimit;
    }
    offset += threadLimit;
  }

  const complete: ExportedThread[] = [];
  for (const [id, thread] of threads) {
    const slots = messages.get(id) ?? [];
    if (slots.length !== thread.message_total || slots.includes(undefined)) {
      throw new ExportError("incomplete");
    }
    complete.push({ ...thread, messages: slots as ExportedMessage[] });
  }
  return JSON.stringify(
    { exported_at: new Date().toISOString(), threads: complete, memories },
    null,
    2,
  );
}

/**
 * Give the browser the text as a file and forget it. The object URL is revoked right after the
 * click, and nothing here keeps a reference to the text, the Blob or the URL.
 */
export function downloadText(
  text: string,
  filename: string,
  doc: Document = document,
  urls: Pick<typeof URL, "createObjectURL" | "revokeObjectURL"> = URL,
): void {
  const url = urls.createObjectURL(new Blob([text], { type: "application/json" }));
  const link = doc.createElement("a");
  link.href = url;
  link.download = filename;
  link.rel = "noopener";
  link.style.display = "none";
  doc.body.append(link);
  link.click();
  link.remove();
  // Revoked after the click has been handled, so the download has started but the URL is gone.
  setTimeout(() => {
    urls.revokeObjectURL(url);
  }, 0);
}

export function exportFilename(now: Date = new Date()): string {
  return `neuron-export-${now.toISOString().slice(0, 10)}.json`;
}
