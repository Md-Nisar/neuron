import { count, list, record, str } from "@/features/data/parse";

/** Shape checks for the knowledge responses (RAG-03). A wrong shape throws; nothing is half-trusted. */

export type Processing = "hosted" | "self_hosted";
export type DocumentStatus = "queued" | "parsing" | "embedding" | "ready" | "failed";

export interface KnowledgeBase {
  kb_id: string;
  /** User text: shown as text, never as HTML. */
  name: string;
  processing: Processing;
  created_at: string;
}

export interface KnowledgeDocument {
  doc_id: string;
  kb_id: string;
  /** User text: shown as text, never as HTML. */
  title: string;
  size_bytes: number;
  page_count: number | null;
  status: DocumentStatus;
  /** A stable code when `failed`, mapped to fixed wording; anything else is dropped. */
  error_code: string | null;
}

export interface DocumentsPage {
  documents: KnowledgeDocument[];
  total: number;
}

export interface DocumentAccepted {
  doc_id: string;
  kb_id: string;
  status: DocumentStatus;
}

// Ids become URL path segments, so only the server's UUID form is accepted.
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const CODE = /^[a-z0-9_]{1,64}$/;
const PROCESSING: readonly Processing[] = ["hosted", "self_hosted"];
const STATUSES: readonly DocumentStatus[] = ["queued", "parsing", "embedding", "ready", "failed"];

function id(source: Record<string, unknown>, key: string): string {
  const value = str(source, key);
  if (!UUID.test(value)) throw new TypeError("shape");
  return value;
}

function oneOf<T extends string>(
  source: Record<string, unknown>,
  key: string,
  allowed: readonly T[],
): T {
  const value = str(source, key);
  if (!(allowed as readonly string[]).includes(value)) throw new TypeError("shape");
  return value as T;
}

export function parseBase(body: unknown): KnowledgeBase {
  const base = record(body);
  return {
    kb_id: id(base, "kb_id"),
    name: str(base, "name"),
    processing: oneOf(base, "processing", PROCESSING),
    created_at: str(base, "created_at"),
  };
}

export function parseBases(body: unknown): KnowledgeBase[] {
  return list(record(body), "bases").map(parseBase);
}

function parseDocument(body: unknown): KnowledgeDocument {
  const doc = record(body);
  const pages = doc["page_count"];
  if (pages !== null && (typeof pages !== "number" || !Number.isInteger(pages) || pages < 0))
    throw new TypeError("shape");
  const code = doc["error_code"];
  return {
    doc_id: id(doc, "doc_id"),
    kb_id: id(doc, "kb_id"),
    title: str(doc, "title"),
    size_bytes: count(doc, "size_bytes"),
    page_count: pages,
    status: oneOf(doc, "status", STATUSES),
    error_code: typeof code === "string" && CODE.test(code) ? code : null,
  };
}

export function parseDocuments(body: unknown): DocumentsPage {
  const page = record(body);
  return { documents: list(page, "documents").map(parseDocument), total: count(page, "total") };
}

export function parseAccepted(body: unknown): DocumentAccepted {
  const accepted = record(body);
  return {
    doc_id: id(accepted, "doc_id"),
    kb_id: id(accepted, "kb_id"),
    status: oneOf(accepted, "status", STATUSES),
  };
}
