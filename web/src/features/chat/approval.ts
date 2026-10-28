import type { ApprovalRequired, PendingAction } from "@/lib/stream";
import { SAFE_ID } from "@/lib/stream";

import { displaySafe } from "./displaySafe";

/** The most arguments text shown to the user. Beyond this nothing is approved, only rejected. */
export const MAX_ARGS_CHARS = 4000;
const MAX_NAME_CHARS = 64;

/**
 * The approval stream endpoint for a decision. Both ids come from the server's payload and are
 * checked again here, because they become URL path segments.
 */
export function approvalStreamPath(approval: ApprovalRequired): string {
  const { thread_id: threadId } = approval;
  const { approval_id: approvalId } = approval.approval;
  if (!SAFE_ID.test(threadId) || !SAFE_ID.test(approvalId)) {
    throw new TypeError("unsafe approval identifiers");
  }
  return `/v1/threads/${encodeURIComponent(threadId)}/approvals/${encodeURIComponent(approvalId)}/stream`;
}

export interface ActionView {
  name: string;
  /** The arguments exactly as the model made them, pretty-printed, with invisible characters made visible. */
  args: string;
  /** False if the arguments are longer than {@link MAX_ARGS_CHARS}: they are cut, so cannot be approved. */
  complete: boolean;
}

export function viewAction(action: PendingAction): ActionView {
  const full = displaySafe(JSON.stringify(action.args, null, 2));
  return {
    name: displaySafe(action.name).slice(0, MAX_NAME_CHARS),
    args: full.slice(0, MAX_ARGS_CHARS),
    complete: full.length <= MAX_ARGS_CHARS && action.name.length <= MAX_NAME_CHARS,
  };
}
