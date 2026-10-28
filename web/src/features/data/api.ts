import { ApiError, apiRequest } from "@/lib/request";

import {
  parseErasure,
  parseExportPage,
  parseMemories,
  type Erasure,
  type ExportPage,
  type MemoriesPage,
} from "./parse";

export interface DataDeps {
  apiUrl: string;
  getAccessToken: () => string | null;
  /** The token is missing or the API refused it (401): the user must sign in again. */
  onSessionEnded: () => void;
  fetch?: typeof fetch | undefined;
}

/** Run an API call with the current token; a missing or refused token ends the session. */
async function call<T>(
  deps: DataDeps,
  options: {
    path: string;
    method: "GET" | "DELETE";
    parse?: (body: unknown) => T;
    signal?: AbortSignal | undefined;
  },
): Promise<T> {
  const token = deps.getAccessToken();
  if (token === null) {
    deps.onSessionEnded();
    throw new ApiError("unauthorized", null, null, null);
  }
  try {
    return await apiRequest<T>({
      baseUrl: deps.apiUrl,
      token,
      fetch: deps.fetch,
      ...options,
    });
  } catch (error) {
    if (error instanceof ApiError && error.kind === "unauthorized") deps.onSessionEnded();
    throw error;
  }
}

export function listMemories(deps: DataDeps, offset: number, limit = 50): Promise<MemoriesPage> {
  return call(deps, {
    path: `/v1/me/memories?limit=${String(limit)}&offset=${String(offset)}`,
    method: "GET",
    parse: parseMemories,
  });
}

export function deleteMemory(deps: DataDeps, id: string): Promise<undefined> {
  return call(deps, { path: `/v1/me/memories/${encodeURIComponent(id)}`, method: "DELETE" });
}

export function eraseAllData(deps: DataDeps): Promise<Erasure> {
  return call(deps, { path: "/v1/me/threads", method: "DELETE", parse: parseErasure });
}

export function exportPage(
  deps: DataDeps,
  page: { limit: number; offset: number; messageLimit: number; messageOffset: number },
  signal?: AbortSignal,
): Promise<ExportPage> {
  const query = new URLSearchParams({
    limit: String(page.limit),
    offset: String(page.offset),
    message_limit: String(page.messageLimit),
    message_offset: String(page.messageOffset),
  });
  return call(deps, {
    path: `/v1/me/export?${query.toString()}`,
    method: "GET",
    parse: parseExportPage,
    signal,
  });
}
