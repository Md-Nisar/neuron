import { FileText, TriangleAlert } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type { Citation } from "@/lib/stream";

import { displaySafe } from "./displaySafe";

/** "p. 3", "pp. 3–4", or nothing when the document has no pages. */
export function pagesText(citation: Pick<Citation, "page_start" | "page_end">): string {
  const { page_start: start, page_end: end } = citation;
  if (start === null) return "";
  return end === null || end === start
    ? `p. ${String(start)}`
    : `pp. ${String(start)}–${String(end)}`;
}

export function citationTitle(citation: Pick<Citation, "title">): string {
  return citation.title === null || citation.title === ""
    ? "Untitled document"
    : displaySafe(citation.title);
}

/**
 * An answer's numbered sources, in the order the server kept them, and a notice when the run
 * searched knowledge but no source supports the answer.
 */
export function Sources({
  citations,
  grounded,
}: {
  citations: Citation[];
  grounded: boolean | null;
}) {
  return (
    <>
      {citations.length > 0 && (
        <ol aria-label="Sources" className="flex flex-wrap gap-1.5">
          {citations.map((citation, index) => {
            const pages = pagesText(citation);
            return (
              // The same passage can be cited twice (found, then read): the position is the key.
              <li key={index} className="max-w-full">
                <Badge variant="outline" className="max-w-full font-normal">
                  <span className="font-semibold tabular-nums">{index + 1}</span>
                  <FileText aria-hidden="true" />
                  <span className="truncate">{citationTitle(citation)}</span>
                  {pages !== "" && <span className="text-muted-foreground">{pages}</span>}
                </Badge>
              </li>
            );
          })}
        </ol>
      )}
      {grounded === false && (
        <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <TriangleAlert aria-hidden="true" className="size-3.5" />
          Not grounded: no passage in your documents supports this answer.
        </p>
      )}
    </>
  );
}
