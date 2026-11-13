import { count, list, record, str } from "@/features/data/parse";

/** Shape checks for the knowledge responses (RAG-03). A wrong shape throws; nothing is half-trusted. */

export type Processing = "hosted" | "self_hosted";
/** A base's text search language (RAG-09.08): Postgres's built-in configurations, fixed at creation. */
export const LANGUAGES = [
  "simple",
  "arabic",
  "armenian",
  "basque",
  "catalan",
  "danish",
  "dutch",
  "english",
  "finnish",
  "french",
  "german",
  "greek",
  "hindi",
  "hungarian",
  "indonesian",
  "irish",
  "italian",
  "lithuanian",
  "nepali",
  "norwegian",
  "portuguese",
  "romanian",
  "russian",
  "serbian",
  "spanish",
  "swedish",
  "tamil",
  "turkish",
  "yiddish",
] as const;
export type Language = (typeof LANGUAGES)[number];
/** The caller's access to a base (RAG-09.03): the server enforces it; the screen follows it. */
export type BaseAccess = "owner" | "admin" | "write" | "read";
export type GrantAccess = Exclude<BaseAccess, "owner">;
export type DocumentStatus = "queued" | "parsing" | "embedding" | "ready" | "failed";

export interface KnowledgeBase {
  kb_id: string;
  /** User text: shown as text, never as HTML. */
  name: string;
  processing: Processing;
  language: Language;
  created_at: string;
  access: BaseAccess;
}

/** A role's access to a base. The role is text the base's admin typed: shown as text. */
export interface Grant {
  role: string;
  access: GrantAccess;
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

/** The passage behind a citation (RAG-03.04): extracted text, shown as text. */
export interface Passage {
  text: string;
  headings: string[];
  page_start: number | null;
  page_end: number | null;
}

// Ids become URL path segments, so only the server's UUID form is accepted.
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const CODE = /^[a-z0-9_]{1,64}$/;
const PROCESSING: readonly Processing[] = ["hosted", "self_hosted"];
const ACCESS: readonly BaseAccess[] = ["owner", "admin", "write", "read"];
const GRANT_ACCESS: readonly GrantAccess[] = ["read", "write", "admin"];
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
    language: oneOf(base, "language", LANGUAGES),
    created_at: str(base, "created_at"),
    access: oneOf(base, "access", ACCESS),
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

function page(source: Record<string, unknown>, key: string): number | null {
  const value = source[key];
  if (value === null) return null;
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0)
    throw new TypeError("shape");
  return value;
}

export function parsePassage(body: unknown): Passage {
  const chunk = record(body);
  const headings = list(chunk, "headings");
  if (!headings.every((heading) => typeof heading === "string")) throw new TypeError("shape");
  return {
    text: str(chunk, "text"),
    headings,
    page_start: page(chunk, "page_start"),
    page_end: page(chunk, "page_end"),
  };
}

export function parseGrants(body: unknown): Grant[] {
  return list(record(body), "grants").map((item) => {
    const grant = record(item);
    return { role: str(grant, "role"), access: oneOf(grant, "access", GRANT_ACCESS) };
  });
}
