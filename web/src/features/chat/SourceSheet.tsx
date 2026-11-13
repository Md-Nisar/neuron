import { LoaderCircle, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import type { DataDeps } from "@/features/data/api";
import { getPassage } from "@/features/knowledge/api";
import type { Passage } from "@/features/knowledge/parse";
import type { Citation } from "@/lib/stream";
import { ApiError } from "@/lib/request";

import { displaySafe } from "./displaySafe";
import { citationTitle, pagesText } from "./Sources";

type Load =
  | { state: "loading" }
  | { state: "ready"; passage: Passage }
  | { state: "unavailable" }
  | { state: "failed" };

/** Gone, never readable, or no longer readable: the same answer, so nothing is confirmed. */
function unavailable(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    (error.kind === "not_found" ||
      error.kind === "forbidden" ||
      error.code === "knowledge_disabled")
  );
}

/**
 * The passage a citation points at, fetched when opened: access is checked by the server each
 * time, so a source the user can no longer read shows no text. The passage is extracted text,
 * shown as text.
 */
export function SourceSheet({
  id,
  number,
  citation,
  deps,
  onClose,
}: {
  id: string;
  number: number;
  citation: Citation;
  deps: DataDeps;
  onClose: () => void;
}) {
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const heading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    heading.current?.focus();
    // One sheet per citation (the list keys it), so this runs once for each.
    let live = true;
    getPassage(deps, citation.doc_id, citation.chunk_id).then(
      (passage) => {
        if (live) setLoad({ state: "ready", passage });
      },
      (error: unknown) => {
        if (live) setLoad({ state: unavailable(error) ? "unavailable" : "failed" });
      },
    );
    return () => {
      live = false;
    };
    // `deps` is stable for the life of the page.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [citation.doc_id, citation.chunk_id]);

  const passage = load.state === "ready" ? load.passage : null;
  const pages = pagesText(passage ?? citation);
  const headings = passage?.headings ?? citation.headings;
  return (
    <section
      id={id}
      aria-labelledby={`${id}-heading`}
      className="animate-in space-y-2 rounded-lg border bg-card p-4 duration-200 fade-in-0"
    >
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <h3
            id={`${id}-heading`}
            ref={heading}
            tabIndex={-1}
            className="truncate text-sm font-semibold outline-none"
          >
            {number}. {citationTitle(citation)}
          </h3>
          {(pages !== "" || headings.length > 0) && (
            <p className="truncate text-xs text-muted-foreground">
              {[pages, ...headings.map(displaySafe)].filter((part) => part !== "").join(" · ")}
            </p>
          )}
          {citation.source_url !== null && (
            // A web page (RAG-10.02): the parser kept only an `https` URL.
            <p className="truncate text-xs text-muted-foreground">
              <a
                href={citation.source_url}
                target="_blank"
                rel="noopener noreferrer nofollow"
                className="underline underline-offset-2 hover:text-foreground"
              >
                {displaySafe(new URL(citation.source_url).host)}
              </a>
              {citation.fetched_at !== null && ` · fetched ${citation.fetched_at.slice(0, 10)}`}
            </p>
          )}
        </div>
        <Button
          type="button"
          variant="ghost"
          size="icon-xs"
          aria-label="Close source"
          onClick={onClose}
        >
          <X />
        </Button>
      </div>
      {load.state === "loading" && (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
          Loading source…
        </p>
      )}
      {passage !== null && (
        <blockquote className="max-h-72 overflow-y-auto border-l-2 pl-3 text-sm leading-6 break-words whitespace-pre-wrap">
          {displaySafe(passage.text)}
        </blockquote>
      )}
      {load.state === "unavailable" && (
        <p role="status" className="text-sm text-muted-foreground">
          Source not available. It may have been deleted, or you no longer have access to it.
        </p>
      )}
      {load.state === "failed" && (
        <p role="alert" className="text-sm text-destructive">
          Could not load the source. Close it and try again.
        </p>
      )}
    </section>
  );
}
