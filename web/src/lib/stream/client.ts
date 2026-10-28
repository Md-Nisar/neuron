import { parseStreamEvent, StreamProtocolError, type StreamEvent } from "./events";
import { DEFAULT_MAX_EVENT_CHARS, parseSse, SseLimitError } from "./sse";

/** Why a stream could not start. Raised before the first byte, so nothing was streamed. */
export type StartErrorKind =
  | "unauthorized" // 401: sign in again
  | "forbidden" // 403: the token lacks the scope
  | "not_found" // 404: unknown or someone else's thread or approval
  | "thread_busy" // 409: another run holds the thread; retry shortly
  | "approval_pending" // 409: decide the pending approval first
  | "conflict" // any other 409
  | "rate_limited" // 429: wait `retryAfterSeconds`
  | "invalid_request" // 400, 413, 422
  | "unavailable" // 503: shutting down or a dependency is down
  | "server_error" // other 5xx
  | "network" // fetch itself failed
  | "unexpected"; // a 2xx that is not an event stream, or any other status

const SAFE_CODE = /^[a-z0-9_]{1,64}$/;
const MAX_RETRY_AFTER_SECONDS = 3600;

export class StreamStartError extends Error {
  constructor(
    readonly kind: StartErrorKind,
    readonly status: number | null,
    /** The server's machine code (`detail`), only if it is a short lowercase token. */
    readonly code: string | null,
    readonly retryAfterSeconds: number | null,
  ) {
    super(`stream could not start: ${kind}`);
    this.name = "StreamStartError";
  }
}

export interface StreamRequest {
  /** The API origin, e.g. `http://127.0.0.1:8000`. The token is sent to this origin only. */
  baseUrl: string;
  /** A path on that origin, e.g. `/v1/agent/stream`. */
  path: string;
  /** The access token, sent only in the `Authorization` header. */
  token: string;
  body?: unknown;
  signal?: AbortSignal | undefined;
  fetch?: typeof fetch;
  maxEventChars?: number;
}

function resolveUrl(baseUrl: string, path: string): URL {
  const base = new URL(baseUrl);
  if (base.protocol !== "https:" && base.protocol !== "http:") {
    throw new TypeError("baseUrl must be http(s)");
  }
  const url = new URL(path, base);
  // A path such as `//other.example/x` would move the request, and the token, to another origin.
  if (url.origin !== base.origin) throw new TypeError("path must stay on the API origin");
  return url;
}

/** Seconds from a `Retry-After` header (delta-seconds or an HTTP date), clamped; null if absent. */
export function parseRetryAfter(value: string | null, now: number = Date.now()): number | null {
  if (value === null) return null;
  const trimmed = value.trim();
  let seconds: number;
  if (/^\d{1,9}$/.test(trimmed)) {
    seconds = Number(trimmed);
  } else {
    // An HTTP date has letters ("Wed, 28 Oct ..."); anything else, such as "-5", is invalid.
    if (!/[A-Za-z]/.test(trimmed)) return null;
    const at = Date.parse(trimmed);
    if (Number.isNaN(at)) return null;
    seconds = Math.ceil((at - now) / 1000);
  }
  return Math.min(Math.max(seconds, 0), MAX_RETRY_AFTER_SECONDS);
}

async function errorCode(response: Response): Promise<string | null> {
  try {
    const body: unknown = await response.json();
    if (typeof body === "object" && body !== null && "detail" in body) {
      const detail = body.detail;
      // Only a short fixed token is surfaced; anything else (a validation list, free text) is not.
      if (typeof detail === "string" && SAFE_CODE.test(detail)) return detail;
    }
  } catch {
    // Not JSON: no code.
  }
  return null;
}

async function startError(response: Response): Promise<StreamStartError> {
  const { status } = response;
  const code = await errorCode(response);
  const retryAfter = parseRetryAfter(response.headers.get("Retry-After"));
  let kind: StartErrorKind;
  if (status === 401) kind = "unauthorized";
  else if (status === 403) kind = "forbidden";
  else if (status === 404) kind = "not_found";
  else if (status === 409) {
    kind =
      code === "thread_busy"
        ? "thread_busy"
        : code === "approval_pending"
          ? "approval_pending"
          : "conflict";
  } else if (status === 429) kind = "rate_limited";
  else if (status === 400 || status === 413 || status === 422) kind = "invalid_request";
  else if (status === 503) kind = "unavailable";
  else if (status >= 500) kind = "server_error";
  else kind = "unexpected";
  return new StreamStartError(kind, status, code, retryAfter);
}

function interruption(cause: unknown): { code: string; retryable: boolean } {
  if (cause instanceof StreamProtocolError) return { code: "protocol_error", retryable: false };
  if (cause instanceof SseLimitError) return { code: "event_too_large", retryable: false };
  return { code: "stream_interrupted", retryable: true };
}

/**
 * POST a request and yield the run's events (`POST /v1/agent/stream` and the approval stream).
 *
 * - Failures before the first byte (401, 403, 404, 409, 429 with `Retry-After`, 5xx, no
 *   network, or a body that is not an event stream) throw {@link StreamStartError}.
 * - Once streaming, the iteration always ends with `done`. If the server sent `error` it is
 *   passed through; if the connection broke or the data was malformed, a synthetic `error`
 *   comes first. The caller never has to guess whether a run ended.
 * - Aborting `signal` ends the iteration quietly: no error, no `done`.
 * - Unknown event names are ignored; `:` heartbeat lines never reach the caller.
 */
export async function* streamRun(request: StreamRequest): AsyncGenerator<StreamEvent, void, void> {
  const { signal } = request;
  const url = resolveUrl(request.baseUrl, request.path);
  const doFetch = request.fetch ?? fetch;

  let response: Response;
  try {
    response = await doFetch(url, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${request.token}`,
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      },
      body: request.body === undefined ? null : JSON.stringify(request.body),
      credentials: "omit",
      cache: "no-store",
      redirect: "error",
      signal: signal ?? null,
    });
  } catch {
    if (signal?.aborted === true) return;
    throw new StreamStartError("network", null, null, null);
  }

  if (!response.ok) throw await startError(response);
  const contentType = response.headers.get("Content-Type") ?? "";
  if (response.body === null || !contentType.toLowerCase().startsWith("text/event-stream")) {
    await response.body?.cancel().catch(() => undefined);
    throw new StreamStartError("unexpected", response.status, null, null);
  }

  let sawError = false;
  let finished = false;
  try {
    const messages = parseSse(response.body, {
      maxEventChars: request.maxEventChars ?? DEFAULT_MAX_EVENT_CHARS,
      signal,
    });
    for await (const message of messages) {
      const event = parseStreamEvent(message.event, message.data);
      if (event === null) continue;
      if (event.type === "error") sawError = true;
      yield event;
      if (event.type === "done") {
        finished = true;
        return;
      }
    }
    if (signal?.aborted === true) return;
  } catch (cause) {
    if (signal?.aborted === true) return;
    if (!sawError) {
      yield { type: "error", data: interruption(cause) };
      sawError = true;
    }
  }
  if (!finished) {
    if (!sawError) yield { type: "error", data: { code: "stream_interrupted", retryable: true } };
    yield { type: "done", data: {} };
  }
}
