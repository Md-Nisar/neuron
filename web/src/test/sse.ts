/** A fake SSE server for tests: `Response` objects over byte streams. No real network. */

const encoder = new TextEncoder();

export function bytes(text: string): Uint8Array {
  return encoder.encode(text);
}

/** One SSE event as the server frames it. */
export function frame(event: string, data: unknown): string {
  return `event: ${event}\r\ndata: ${JSON.stringify(data)}\r\n\r\n`;
}

/** A stream that delivers `chunks` in order, then either closes or errors. */
export function streamOf(
  chunks: (string | Uint8Array)[],
  end: "close" | Error = "close",
  onCancel?: () => void,
): ReadableStream<Uint8Array> {
  let index = 0;
  return new ReadableStream<Uint8Array>({
    pull(controller) {
      const next = chunks[index];
      if (next !== undefined) {
        index += 1;
        controller.enqueue(typeof next === "string" ? bytes(next) : next);
      } else if (end === "close") {
        controller.close();
      } else {
        controller.error(end);
      }
    },
    cancel() {
      onCancel?.();
    },
  });
}

/** A stream the test feeds by hand, to abort in the middle of a run. */
export function controlledStream(onCancel?: () => void): {
  stream: ReadableStream<Uint8Array>;
  push: (text: string) => void;
} {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const stream = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c;
    },
    cancel() {
      onCancel?.();
    },
  });
  return {
    stream,
    push: (text) => {
      controller.enqueue(bytes(text));
    },
  };
}

export function sseResponse(body: ReadableStream<Uint8Array>, status = 200): Response {
  return new Response(body, { status, headers: { "Content-Type": "text/event-stream" } });
}

export function jsonResponse(
  status: number,
  body: unknown,
  headers: Record<string, string> = {},
): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

export async function collect<T>(source: AsyncIterable<T>): Promise<T[]> {
  const items: T[] = [];
  for await (const item of source) items.push(item);
  return items;
}
