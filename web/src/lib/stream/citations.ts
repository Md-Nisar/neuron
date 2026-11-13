/**
 * An answer's citations (RAG-05.02), as the `final` event and thread history carry them. The
 * server keeps only citations a knowledge tool returned in the run; this checks their shape.
 * Ids become URL path segments (the chunk route), so only the server's UUID form is accepted.
 * `cite_id` is not kept: it means nothing after the run.
 */

export interface Citation {
  doc_id: string;
  chunk_id: string;
  /** User text: shown through `displaySafe`. */
  title: string | null;
  headings: string[];
  page_start: number | null;
  page_end: number | null;
  /** A web page's address (RAG-10.02): only an `https` URL is kept, so it is safe as a link. */
  source_url: string | null;
  /** When the page was fetched, as the server's ISO 8601 text. */
  fetched_at: string | null;
}

export interface Grounding {
  citations: Citation[];
  /** Null when the run did not search knowledge; false when it did and kept no citation. */
  grounded: boolean | null;
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

function shape(): never {
  throw new TypeError("shape");
}

function page(value: unknown): number | null {
  if (value === null || value === undefined) return null;
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : shape();
}

/** An `https` URL, else null: anything else is never used as a link. */
export function httpsUrl(value: unknown): string | null {
  if (typeof value !== "string") return null;
  try {
    return new URL(value).protocol === "https:" ? value : null;
  } catch {
    return null;
  }
}

function parseCitation(value: unknown): Citation {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return shape();
  const item = value as Record<string, unknown>;
  const { doc_id, chunk_id, title, headings } = item;
  if (
    typeof doc_id !== "string" ||
    !UUID.test(doc_id) ||
    typeof chunk_id !== "string" ||
    !UUID.test(chunk_id) ||
    (title !== null && title !== undefined && typeof title !== "string") ||
    !Array.isArray(headings) ||
    !headings.every((heading) => typeof heading === "string")
  ) {
    return shape();
  }
  return {
    doc_id,
    chunk_id,
    title: title ?? null,
    headings,
    page_start: page(item["page_start"]),
    page_end: page(item["page_end"]),
    source_url: httpsUrl(item["source_url"]),
    fetched_at: typeof item["fetched_at"] === "string" ? item["fetched_at"] : null,
  };
}

/**
 * The citation fields of a `final` payload or a history message; throws `TypeError` on a bad
 * shape. A schema version this client does not know is shown as no citations.
 */
export function parseGrounding(source: Record<string, unknown>): Grounding {
  const { citations, citation_schema_version: version, grounded } = source;
  if (grounded !== null && grounded !== undefined && typeof grounded !== "boolean") shape();
  if (version !== 1) return { citations: [], grounded: null };
  if (!Array.isArray(citations)) shape();
  return { citations: citations.map(parseCitation), grounded: grounded ?? null };
}
