/** A dispatched server-sent event: its name and the joined `data` lines. */
export interface SseMessage {
  event: string;
  data: string;
}

export interface ParseOptions {
  /** Longest line or event (in UTF-16 units) accepted before the stream is refused. */
  maxEventChars?: number;
  /** Aborting cancels the underlying reader, which ends the iteration. */
  signal?: AbortSignal | undefined;
}

export const DEFAULT_MAX_EVENT_CHARS = 1_048_576;

/** The stream broke the SSE framing limits (an event or line larger than allowed). */
export class SseLimitError extends Error {
  constructor() {
    super("server-sent event exceeds the size limit");
    this.name = "SseLimitError";
  }
}

const LINE_END = /\r\n|\r|\n/g;

/**
 * Parse a byte stream as server-sent events (WHATWG HTML, "Server-sent events").
 *
 * Handles chunks split anywhere (including inside a multi-byte character or a CRLF), `:`
 * comment lines (heartbeats), multi-line `data`, and the default `message` event name. An
 * event without its terminating blank line is dropped, never half-delivered. `id` and `retry`
 * are ignored: reconnecting is not resuming (ADR 0010, decision 4).
 */
export async function* parseSse(
  body: ReadableStream<Uint8Array>,
  options: ParseOptions = {},
): AsyncGenerator<SseMessage, void, void> {
  const maxChars = options.maxEventChars ?? DEFAULT_MAX_EVENT_CHARS;
  const reader = body.getReader();
  const decoder = new TextDecoder("utf-8");
  const onAbort = (): void => {
    reader.cancel().catch(() => undefined);
  };
  options.signal?.addEventListener("abort", onAbort, { once: true });

  let buffer = "";
  let skipLf = false;
  let eventName = "";
  let dataLines: string[] = [];
  let dataChars = 0;

  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (options.signal?.aborted === true) return;
      if (done) return;
      buffer += decoder.decode(value, { stream: true });
      if (skipLf) {
        if (buffer.startsWith("\n")) buffer = buffer.slice(1);
        skipLf = false;
      }

      let consumed = 0;
      LINE_END.lastIndex = 0;
      for (let match = LINE_END.exec(buffer); match !== null; match = LINE_END.exec(buffer)) {
        const line = buffer.slice(consumed, match.index);
        consumed = LINE_END.lastIndex;
        // A lone CR at the very end may be the first half of a CRLF split across chunks.
        if (match[0] === "\r" && consumed === buffer.length) skipLf = true;

        if (line === "") {
          if (dataLines.length > 0) {
            yield { event: eventName === "" ? "message" : eventName, data: dataLines.join("\n") };
          }
          eventName = "";
          dataLines = [];
          dataChars = 0;
          continue;
        }
        if (line.startsWith(":")) continue;
        const colon = line.indexOf(":");
        const field = colon === -1 ? line : line.slice(0, colon);
        let fieldValue = colon === -1 ? "" : line.slice(colon + 1);
        if (fieldValue.startsWith(" ")) fieldValue = fieldValue.slice(1);
        if (field === "event") {
          eventName = fieldValue;
        } else if (field === "data") {
          dataLines.push(fieldValue);
          dataChars += fieldValue.length + 1;
          if (dataChars > maxChars) throw new SseLimitError();
        }
      }
      buffer = buffer.slice(consumed);
      if (buffer.length > maxChars) throw new SseLimitError();
    }
  } finally {
    options.signal?.removeEventListener("abort", onAbort);
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}
