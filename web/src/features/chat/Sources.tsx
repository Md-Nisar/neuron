import { FileText, Globe, TriangleAlert } from "lucide-react";
import { useId, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import type { DataDeps } from "@/features/data/api";
import type { Citation } from "@/lib/stream";

import { displaySafe } from "./displaySafe";
import { SourceSheet } from "./SourceSheet";

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
 * searched knowledge but no source supports the answer. With `deps`, a chip opens its passage.
 */
export function Sources({
  citations,
  grounded,
  deps,
}: {
  citations: Citation[];
  grounded: boolean | null;
  deps?: DataDeps | undefined;
}) {
  const [open, setOpen] = useState<number | null>(null);
  const chips = useRef<(HTMLButtonElement | null)[]>([]);
  const sheetId = useId();
  const shown = open === null ? undefined : citations[open];
  return (
    <>
      {citations.length > 0 && (
        <ol aria-label="Sources" className="flex flex-wrap gap-1.5">
          {citations.map((citation, index) => {
            const pages = pagesText(citation);
            return (
              // The same passage can be cited twice (found, then read): the position is the key.
              <li key={index} className="max-w-full">
                {deps === undefined ? (
                  <Badge variant="outline" className="max-w-full font-normal">
                    {chip(index, citation, pages)}
                  </Badge>
                ) : (
                  <button
                    type="button"
                    ref={(node) => {
                      chips.current[index] = node;
                    }}
                    aria-expanded={open === index}
                    aria-controls={open === index ? sheetId : undefined}
                    className="group max-w-full cursor-pointer rounded-md outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
                    onClick={() => {
                      setOpen(open === index ? null : index);
                    }}
                  >
                    <Badge
                      variant="outline"
                      className="max-w-full font-normal group-hover:bg-accent group-aria-expanded:border-primary"
                    >
                      {chip(index, citation, pages)}
                    </Badge>
                  </button>
                )}
              </li>
            );
          })}
        </ol>
      )}
      {deps !== undefined && open !== null && shown !== undefined && (
        <SourceSheet
          key={open}
          id={sheetId}
          number={open + 1}
          citation={shown}
          deps={deps}
          onClose={() => {
            chips.current[open]?.focus();
            setOpen(null);
          }}
        />
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

function chip(index: number, citation: Citation, pages: string) {
  return (
    <>
      <span className="font-semibold tabular-nums">{index + 1}</span>
      {citation.source_url === null ? (
        <FileText aria-hidden="true" />
      ) : (
        <Globe aria-hidden="true" />
      )}
      <span className="truncate">{citationTitle(citation)}</span>
      {pages !== "" && <span className="text-muted-foreground">{pages}</span>}
    </>
  );
}
