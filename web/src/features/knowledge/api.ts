import { call, type DataDeps } from "@/features/data/api";

import {
  parseAccepted,
  parseBase,
  parseBases,
  parseDocuments,
  parseGrants,
  parsePassage,
  type DocumentAccepted,
  type Grant,
  type DocumentsPage,
  type KnowledgeBase,
  type Language,
  type Passage,
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
  language: Language = "simple",
): Promise<KnowledgeBase> {
  return call(deps, {
    path: "/v1/knowledge/bases",
    method: "POST",
    body: { name, processing, language },
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

/** Tombstone a document; its file, chunks and index entries are purged soon after. */
export function deleteDocument(deps: DataDeps, docId: string): Promise<undefined> {
  return call(deps, {
    path: `/v1/knowledge/documents/${encodeURIComponent(docId)}`,
    method: "DELETE",
  });
}

/** The passage a citation points at. Access is checked again on every call. */
export function getPassage(deps: DataDeps, docId: string, chunkId: string): Promise<Passage> {
  const path = `/v1/knowledge/documents/${encodeURIComponent(docId)}/chunks/${encodeURIComponent(chunkId)}`;
  return call(deps, { path, method: "GET", parse: parsePassage });
}

/** A base's role grants; only its owner and `admin` roles may read them. */
export function getGrants(deps: DataDeps, kbId: string): Promise<Grant[]> {
  return call(deps, { path: `${base(kbId)}/grants`, method: "GET", parse: parseGrants });
}

/** Replace every role grant of a base: a role left out loses its access from its next request. */
export function setGrants(deps: DataDeps, kbId: string, grants: Grant[]): Promise<Grant[]> {
  return call(deps, {
    path: `${base(kbId)}/grants`,
    method: "PUT",
    body: { grants },
    parse: parseGrants,
  });
}
