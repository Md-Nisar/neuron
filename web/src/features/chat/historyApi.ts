import { call, type DataDeps } from "@/features/data/api";
import { parseApprovalBody, SAFE_ID, type ApprovalRequired } from "@/lib/stream";

import { parseHistory, type HistoryPage } from "./history";

/** The most messages fetched in one request (the server's cap). */
export const HISTORY_PAGE = 100;

function threadPath(threadId: string): string {
  // The id comes from the server's own list; it is checked again because it joins a URL path.
  if (!SAFE_ID.test(threadId)) throw new TypeError("unsafe thread id");
  return `/v1/threads/${encodeURIComponent(threadId)}`;
}

export async function getHistory(
  deps: DataDeps,
  threadId: string,
  offset: number,
  signal?: AbortSignal,
): Promise<HistoryPage> {
  return await call(deps, {
    path: `${threadPath(threadId)}/messages?limit=${String(HISTORY_PAGE)}&offset=${String(offset)}`,
    method: "GET",
    parse: parseHistory,
    signal,
  });
}

/** The approval the thread is paused on; `not_found` if nothing is pending (or it is not yours). */
export async function getPendingApproval(
  deps: DataDeps,
  threadId: string,
): Promise<ApprovalRequired> {
  const approval = await call(deps, {
    path: `${threadPath(threadId)}/approval`,
    method: "GET",
    parse: parseApprovalBody,
  });
  // A card for some other thread must never be shown under this one.
  if (approval.thread_id !== threadId) throw new TypeError("shape");
  return approval;
}
