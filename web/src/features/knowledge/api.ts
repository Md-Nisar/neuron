import { call, type DataDeps } from "@/features/data/api";

import {
  parseAccepted,
  parseBase,
  parseBases,
  parseDocuments,
  type DocumentAccepted,
  type DocumentsPage,
  type KnowledgeBase,
  type Processing,
} from "./parse";

/** The knowledge routes (RAG-03), with the same token handling as every other API call. */

const base = (kbId: string) => `/v1/knowledge/bases/${encodeURIComponent(kbId)}`;

export function listBases(deps: DataDeps): Promise<KnowledgeBase[]> {
  return call(deps, { path: "/v1/knowledge/bases", method: "GET", parse: parseBases });
}

export function createBase(
  deps: DataDeps,
  name: string,
  processing: Processing,
): Promise<KnowledgeBase> {
  return call(deps, {
    path: "/v1/knowledge/bases",
    method: "POST",
    body: { name, processing },
    parse: parseBase,
  });
}

export function renameBase(deps: DataDeps, kbId: string, name: string): Promise<KnowledgeBase> {
  return call(deps, { path: base(kbId), method: "PATCH", body: { name }, parse: parseBase });
}

export function deleteBase(deps: DataDeps, kbId: string): Promise<undefined> {
  return call(deps, { path: base(kbId), method: "DELETE" });
}

export function listDocuments(
  deps: DataDeps,
  kbId: string,
  offset: number,
  limit = 50,
): Promise<DocumentsPage> {
  return call(deps, {
    path: `${base(kbId)}/documents?limit=${String(limit)}&offset=${String(offset)}`,
    method: "GET",
    parse: parseDocuments,
  });
}

/**
 * Upload one file. The caller keeps `idempotencyKey` for the file, so a retry after a lost
 * response returns the first document instead of storing a second one.
 */
export function uploadDocument(
  deps: DataDeps,
  kbId: string,
  file: File,
  idempotencyKey: string,
): Promise<DocumentAccepted> {
  const form = new FormData();
  form.append("file", file, file.name);
  return call(deps, {
    path: `${base(kbId)}/documents`,
    method: "POST",
    form,
    idempotencyKey,
    parse: parseAccepted,
  });
}
