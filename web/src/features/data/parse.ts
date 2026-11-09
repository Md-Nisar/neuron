import { SAFE_ID } from "@/lib/stream";

/** Shape checks for the data-rights responses. A wrong shape throws; nothing is half-trusted. */

export interface Memory {
  id: string;
  text: string;
  created_at: string;
}

export interface MemoriesPage {
  memories: Memory[];
  total: number;
}

export interface ExportedMessage {
  role: string;
  content: string;
  tool_calls?: unknown[];
}

export interface ExportedThread {
  thread_id: string;
  created_at: string;
  updated_at: string;
  message_total: number;
  title?: string;
  messages: ExportedMessage[];
}

/** A document's metadata in the export; never its contents. */
export interface ExportedDocument {
  doc_id: string;
  title: string;
  mime_type: string;
  size_bytes: number;
  page_count: number | null;
  status: string;
  error_code: string | null;
  created_at: string;
  updated_at: string;
}

export interface ExportedKnowledgeBase {
  kb_id: string;
  name: string;
  processing: string;
  created_at: string;
  documents: ExportedDocument[];
}

export interface ExportPage {
  threads: ExportedThread[];
  total_threads: number;
  has_more_messages: boolean;
  memories: Memory[];
  knowledge_bases: ExportedKnowledgeBase[];
}

/** The knowledge part of an erase: `purge_pending` while files are still being deleted. */
export interface KnowledgeErasure {
  erased_base_count: number;
  erased_document_count: number;
  purge_pending: boolean;
}

export interface Erasure {
  erased_count: number;
  skipped_busy_count: number;
  erased_memory_count: number;
  /** Null when knowledge is off (or the server predates it). */
  knowledge: KnowledgeErasure | null;
  complete: boolean;
}

export function record(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value))
    throw new TypeError("shape");
  return value as Record<string, unknown>;
}

export function str(source: Record<string, unknown>, key: string): string {
  const value = source[key];
  if (typeof value !== "string") throw new TypeError("shape");
  return value;
}

export function count(source: Record<string, unknown>, key: string): number {
  const value = source[key];
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0)
    throw new TypeError("shape");
  return value;
}

export function list(source: Record<string, unknown>, key: string): unknown[] {
  const value = source[key];
  if (!Array.isArray(value)) throw new TypeError("shape");
  return value as unknown[];
}

function parseMemory(value: unknown): Memory {
  const item = record(value);
  const id = str(item, "id");
  // The id becomes a URL path segment when deleting.
  if (!SAFE_ID.test(id)) throw new TypeError("shape");
  return { id, text: str(item, "text"), created_at: str(item, "created_at") };
}

export function parseMemories(body: unknown): MemoriesPage {
  const page = record(body);
  return { memories: list(page, "memories").map(parseMemory), total: count(page, "total") };
}

function parseThread(value: unknown): ExportedThread {
  const thread = record(value);
  return {
    thread_id: str(thread, "thread_id"),
    created_at: str(thread, "created_at"),
    updated_at: str(thread, "updated_at"),
    message_total: count(thread, "message_total"),
    ...(typeof thread["title"] === "string" ? { title: thread["title"] } : {}),
    messages: list(thread, "messages").map((message): ExportedMessage => {
      const item = record(message);
      const calls = item["tool_calls"];
      return {
        role: str(item, "role"),
        content: str(item, "content"),
        ...(Array.isArray(calls) ? { tool_calls: calls as unknown[] } : {}),
      };
    }),
  };
}

function nullable<T>(
  source: Record<string, unknown>,
  key: string,
  read: (s: Record<string, unknown>, k: string) => T,
): T | null {
  return source[key] === null ? null : read(source, key);
}

function parseDocument(value: unknown): ExportedDocument {
  const doc = record(value);
  return {
    doc_id: str(doc, "doc_id"),
    title: str(doc, "title"),
    mime_type: str(doc, "mime_type"),
    size_bytes: count(doc, "size_bytes"),
    page_count: nullable(doc, "page_count", count),
    status: str(doc, "status"),
    error_code: nullable(doc, "error_code", str),
    created_at: str(doc, "created_at"),
    updated_at: str(doc, "updated_at"),
  };
}

function parseKnowledgeBase(value: unknown): ExportedKnowledgeBase {
  const base = record(value);
  return {
    kb_id: str(base, "kb_id"),
    name: str(base, "name"),
    processing: str(base, "processing"),
    created_at: str(base, "created_at"),
    documents: list(base, "documents").map(parseDocument),
  };
}

export function parseExportPage(body: unknown): ExportPage {
  const page = record(body);
  const more = page["has_more_messages"];
  if (typeof more !== "boolean") throw new TypeError("shape");
  const memories = page["memories"];
  return {
    threads: list(page, "threads").map(parseThread),
    total_threads: count(page, "total_threads"),
    has_more_messages: more,
    memories: Array.isArray(memories) ? (memories as unknown[]).map(parseMemory) : [],
    knowledge_bases:
      page["knowledge_bases"] === undefined
        ? []
        : list(page, "knowledge_bases").map(parseKnowledgeBase),
  };
}

function parseKnowledgeErasure(value: unknown): KnowledgeErasure | null {
  if (value === undefined || value === null) return null;
  const result = record(value);
  const pending = result["purge_pending"];
  if (typeof pending !== "boolean") throw new TypeError("shape");
  return {
    erased_base_count: count(result, "erased_base_count"),
    erased_document_count: count(result, "erased_document_count"),
    purge_pending: pending,
  };
}

export function parseErasure(body: unknown): Erasure {
  const result = record(body);
  const complete = result["complete"];
  if (typeof complete !== "boolean") throw new TypeError("shape");
  return {
    erased_count: count(result, "erased_count"),
    skipped_busy_count: count(result, "skipped_busy_count"),
    erased_memory_count: count(result, "erased_memory_count"),
    knowledge: parseKnowledgeErasure(result["knowledge"]),
    complete,
  };
}
