import { dataErrorText } from "@/features/data/messages";
import { ApiError } from "@/lib/request";

/** Fixed wording for a failed conversation call. Server text is never shown. */
export function threadErrorText(error: unknown, action: "list" | "rename" | "delete"): string {
  if (error instanceof ApiError) {
    if (error.kind === "not_found" && action !== "list") {
      return "That conversation no longer exists.";
    }
    if (error.kind === "invalid_request" && action === "rename") {
      return "That title can't be used. Use 1 to 80 plain characters.";
    }
    if (error.kind === "forbidden" && action === "rename") {
      return "You do not have permission to rename conversations.";
    }
  }
  return dataErrorText(error);
}

export const TITLE_MAX_CHARS = 80;
