import type { KnowledgeDocument } from "./parse";

/** A byte count as people read it: B, KB or MB. */
export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${String(bytes)} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const DAY = 86_400_000;

/** A timestamp as a short date ("12 Nov 2026"), or "Today" / "Yesterday"; "" if unreadable. */
export function formatDate(iso: string, now: Date = new Date()): string {
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return "";
  const days = Math.floor(
    (Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()) -
      Date.UTC(when.getFullYear(), when.getMonth(), when.getDate())) /
      DAY,
  );
  if (days === 0) return "Today";
  if (days === 1) return "Yesterday";
  return when.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

/** The full local date and time, for a tooltip or `<time title>`. */
export function formatDateTime(iso: string): string {
  const when = new Date(iso);
  return Number.isNaN(when.getTime()) ? "" : when.toLocaleString();
}

const KINDS: [RegExp, string][] = [
  [/\.pdf$/i, "PDF"],
  [/\.docx$/i, "Word"],
  [/\.xlsx$/i, "Excel"],
  [/\.pptx$/i, "PowerPoint"],
  [/\.csv$/i, "CSV"],
  [/\.(md|markdown)$/i, "Markdown"],
  [/\.txt$/i, "Text"],
];

/** What kind of document it is, for its row: a web page, else from its file name. */
export function documentKind(doc: Pick<KnowledgeDocument, "title" | "source_url">): string {
  if (doc.source_url !== null) return "Web page";
  return KINDS.find(([pattern]) => pattern.test(doc.title))?.[1] ?? "File";
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${String(n)} ${n === 1 ? one : many}`;
}

/**
 * A safe name to save a document under. Titles are untrusted (a file name or a fetched page's
 * title): control and format characters (bidi overrides, zero-width) and path or reserved
 * characters become `_`, as the server's `Content-Disposition` fallback does for ASCII.
 */
export function downloadName(title: string): string {
  const safe = title
    .replace(/[\p{C}\\/:*?"<>|]/gu, "_")
    .slice(0, 150)
    .replace(/^[\s.]+|[\s.]+$/g, "");
  return safe === "" ? "download" : safe;
}
