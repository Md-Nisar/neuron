import { dataErrorText } from "@/features/data/messages";
import { ApiError } from "@/lib/request";

import type { Processing } from "./parse";

/** Fixed wording for a failed knowledge call. Server text is never shown. */
export function knowledgeErrorText(error: unknown): string {
  if (error instanceof ApiError) {
    switch (error.code) {
      case "knowledge_disabled":
        return "Knowledge bases are turned off for this service.";
      case "knowledge_base_not_found":
        return "That knowledge base no longer exists.";
      case "knowledge_base_limit_reached":
        return "You have reached the limit of knowledge bases. Delete one to create another.";
    }
    if (error.kind === "invalid_request")
      return "That name can't be used. Use 1 to 80 plain characters.";
    if (error.kind === "forbidden") return "You do not have permission to manage knowledge bases.";
  }
  return dataErrorText(error);
}

export const NAME_MAX_CHARS = 80;

/** Where a base's text is processed, said before anything is uploaded to it. */
export const PROCESSING_TEXT: Record<Processing, { label: string; detail: string }> = {
  hosted: {
    label: "Hosted",
    detail: "Text from your files is sent to the configured embedding provider to be indexed.",
  },
  self_hosted: {
    label: "Self-hosted only",
    detail:
      "Text from your files is indexed only by models this service runs itself. If none is set up, processing fails instead of using a hosted provider.",
  },
};

/** Why a document failed: one fixed wording for every code, for now. */
export const DOCUMENT_FAILED = "Processing failed. Upload the file again.";

/** Why an upload was refused. */
export const uploadErrorText = knowledgeErrorText;
