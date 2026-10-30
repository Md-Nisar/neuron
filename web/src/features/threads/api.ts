import { call, type DataDeps } from "@/features/data/api";

import { parseRenamed, parseThreads, type ThreadsPage } from "./parse";

export type ThreadDeps = DataDeps;

export function listThreads(
  deps: ThreadDeps,
  offset: number,
  limit = 30,
  signal?: AbortSignal,
): Promise<ThreadsPage> {
  return call(deps, {
    path: `/v1/me/threads?limit=${String(limit)}&offset=${String(offset)}`,
    method: "GET",
    parse: parseThreads,
    signal,
  });
}

/** Rename; resolves with the title as the server stored it. */
export function renameThread(deps: ThreadDeps, id: string, title: string): Promise<string> {
  return call(deps, {
    path: `/v1/threads/${encodeURIComponent(id)}`,
    method: "PATCH",
    body: { title },
    parse: parseRenamed,
  });
}

export function deleteThread(deps: ThreadDeps, id: string): Promise<undefined> {
  return call(deps, { path: `/v1/threads/${encodeURIComponent(id)}`, method: "DELETE" });
}
