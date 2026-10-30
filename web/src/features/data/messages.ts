import { failureText } from "@/features/chat/messages";
import { ApiError } from "@/lib/request";

import { ExportError } from "./exportData";

/** Fixed wording for a failed data-rights call. Server text is never shown. */
export function dataErrorText(error: unknown): string {
  if (error instanceof ExportError) {
    return error.reason === "too_large"
      ? "Your data is too large to export from here."
      : "The export could not be completed, so no file was made. Please try again.";
  }
  if (error instanceof ApiError) {
    if (error.kind === "not_found" && error.code === "memory_disabled") {
      return "Memory is turned off for this service.";
    }
    if (error.status === 413) return "Your data is too large to export from here.";
    if (error.kind === "unexpected") return "Something went wrong. Please try again.";
    return failureText({ kind: error.kind, retryAfterSeconds: error.retryAfterSeconds });
  }
  return "Something went wrong. Please try again.";
}

export const ERASE_PHRASE = "erase my data";
