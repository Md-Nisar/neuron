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
      case "knowledge_document_not_found":
        return "That document no longer exists.";
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

const TOO_LARGE = "The file is too large to process.";
const UNREADABLE = "The file could not be read, so uploading it again won't help.";
const UNSUPPORTED =
  "This file type isn't supported. Use PDF, Word, Excel, PowerPoint, text or Markdown.";

/** Why a document failed, from its stable `error_code` (README, "Knowledge files"). */
const FAILURES: Record<string, string> = {
  encrypted_pdf: "The PDF is password-protected. Remove the password and upload it again.",
  archive_refused: "Archives such as .zip can't be uploaded. Upload the files inside instead.",
  macro_refused: "Files with macros can't be uploaded. Save a copy without macros and upload that.",
  unsupported_media_type: UNSUPPORTED,
  media_type_mismatch: UNSUPPORTED,
  empty_file: "The file is empty.",
  file_too_large: TOO_LARGE,
  too_many_pages: TOO_LARGE,
  page_too_long: TOO_LARGE,
  too_many_blocks: TOO_LARGE,
  decompression_limit: TOO_LARGE,
  no_text: "No text could be found in this file.",
  parser_timeout: UNREADABLE,
  parser_failed: UNREADABLE,
  parser_output_invalid: UNREADABLE,
  parser_output_too_large: UNREADABLE,
  parser_unavailable: "Document processing was unavailable. Upload the file again later.",
  parser_not_configured: "Document processing is not set up on this service.",
  processing_locality_forbidden:
    "This knowledge base is self-hosted only, and this service has no self-hosted embedding model.",
};

export function documentFailureText(code: string | null): string {
  if (code !== null && Object.hasOwn(FAILURES, code)) return FAILURES[code] ?? "";
  if (code?.startsWith("embedding_")) return "Indexing failed. Upload the file again later.";
  if (code?.startsWith("blob_")) return "The stored file could not be read. Upload it again.";
  return "Processing failed. Upload the file again.";
}

const UPLOAD_REFUSALS: Record<string, string> = {
  byte_quota_exceeded: "You have used all your document storage. Delete documents to upload more.",
  document_quota_exceeded: "You have reached your document limit. Delete documents to upload more.",
  page_quota_exceeded: "You have reached your page limit. Delete documents to upload more.",
  ingestion_concurrency_exceeded:
    "Too many of your documents are still being processed. Try again in a moment.",
  upload_busy: "The service is busy with other uploads. Try again in a moment.",
  upload_timeout: "The upload took too long. Try again.",
  payload_too_large: TOO_LARGE,
};

/** Why an upload was refused: quotas and file checks first, then the general messages. */
export function uploadErrorText(error: unknown): string {
  const code = error instanceof ApiError ? error.code : null;
  if (code !== null && Object.hasOwn(UPLOAD_REFUSALS, code)) return UPLOAD_REFUSALS[code] ?? "";
  if (code !== null && Object.hasOwn(FAILURES, code)) return FAILURES[code] ?? "";
  return knowledgeErrorText(error);
}
