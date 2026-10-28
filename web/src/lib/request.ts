import { resolveUrl, startError, type StartErrorKind } from "@/lib/stream/client";

/** A JSON API call that did not succeed. Reasons are fixed kinds; server text is never kept. */
export class ApiError extends Error {
  constructor(
    readonly kind: StartErrorKind,
    readonly status: number | null,
    /** The server's machine code (`detail`) if it is a short lowercase token, e.g. `memory_disabled`. */
    readonly code: string | null,
    readonly retryAfterSeconds: number | null,
  ) {
    super(`request failed: ${kind}`);
    this.name = "ApiError";
  }
}

export interface RequestOptions<T> {
  baseUrl: string;
  path: string;
  token: string;
  method: "GET" | "DELETE" | "PATCH" | "POST";
  /** A JSON request body (sent with `PATCH` or `POST`). */
  body?: unknown;
  /** Turns the parsed JSON body into `T`, or throws if it has the wrong shape. */
  parse?: (body: unknown) => T;
  signal?: AbortSignal | undefined;
  fetch?: typeof fetch | undefined;
}

/**
 * One authenticated JSON call. The token goes in the `Authorization` header, only to the API's
 * origin (a path that would change origin is refused), with no cookies, no redirects and no
 * caching. A `204` resolves with `undefined`.
 */
export async function apiRequest<T = undefined>(options: RequestOptions<T>): Promise<T> {
  const url = resolveUrl(options.baseUrl, options.path);
  const doFetch = options.fetch ?? fetch;
  let response: Response;
  try {
    response = await doFetch(url, {
      method: options.method,
      headers: {
        Authorization: `Bearer ${options.token}`,
        Accept: "application/json",
        ...(options.body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      ...(options.body === undefined ? {} : { body: JSON.stringify(options.body) }),
      credentials: "omit",
      cache: "no-store",
      redirect: "error",
      signal: options.signal ?? null,
    });
  } catch {
    throw new ApiError("network", null, null, null);
  }
  if (!response.ok) {
    const failure = await startError(response);
    throw new ApiError(failure.kind, failure.status, failure.code, failure.retryAfterSeconds);
  }
  if (response.status === 204 || options.parse === undefined) return undefined as T;
  try {
    return options.parse((await response.json()) as unknown);
  } catch {
    throw new ApiError("unexpected", response.status, null, null);
  }
}
