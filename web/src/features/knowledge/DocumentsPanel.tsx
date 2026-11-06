import { FileUp, Info, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { displaySafe } from "@/features/chat/displaySafe";
import type { DataDeps } from "@/features/data/api";
import { ApiError } from "@/lib/request";
import { cn } from "@/lib/utils";

import { deleteDocument, listDocuments, uploadDocument } from "./api";
import {
  documentFailureText,
  knowledgeErrorText,
  PROCESSING_TEXT,
  uploadErrorText,
} from "./messages";
import type { DocumentStatus, KnowledgeBase, KnowledgeDocument } from "./parse";

export const POLL_MS = 2000;
const PAGE = 100;
const STATUS: Record<DocumentStatus, string> = {
  queued: "Queued",
  parsing: "Reading",
  embedding: "Indexing",
  ready: "Ready",
  failed: "Failed",
};
const settled = (doc: KnowledgeDocument) => doc.status === "ready" || doc.status === "failed";

function size(bytes: number): string {
  if (bytes < 1024) return `${String(bytes)} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** One base's documents: upload by drop or picker, and each one's status, kept up to date. */
export function DocumentsPanel({ deps, base }: { deps: DataDeps; base: KnowledgeBase }) {
  const [docs, setDocs] = useState<KnowledgeDocument[]>([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [tick, setTick] = useState(0);
  // Counts finished loads, failed ones too, so polling goes on after a failed refresh.
  const [loads, setLoads] = useState(0);
  const [confirming, setConfirming] = useState<string | null>(null);
  const deleting = useRef(false);
  const heading = useRef<HTMLHeadingElement>(null);
  const trash = useRef(new Map<string, HTMLButtonElement>());
  const cancelled = useRef<string | null>(null);
  const pending = docs.some((doc) => !settled(doc));

  useEffect(() => {
    let live = true;
    listDocuments(deps, base.kb_id, 0, PAGE).then(
      (page) => {
        if (!live) return;
        setDocs(page.documents);
        setTotal(page.total);
        setLoads((n) => n + 1);
      },
      (failure: unknown) => {
        if (!live) return;
        setError(knowledgeErrorText(failure));
        setLoads((n) => n + 1);
      },
    );
    return () => {
      live = false;
    };
    // `deps` is stable for the life of the page.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [base.kb_id, tick]);

  // While a document is still being processed, look again after a short wait.
  useEffect(() => {
    if (!pending) return;
    const timer = setTimeout(() => {
      setTick((n) => n + 1);
    }, POLL_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [pending, loads]);

  // Cancelling the confirm step removes the focused control: return to the row's delete button.
  useEffect(() => {
    if (confirming !== null || cancelled.current === null) return;
    trash.current.get(cancelled.current)?.focus();
    cancelled.current = null;
  }, [confirming]);

  /** Each file in turn; every refusal in the batch stays shown, and each upload is listed as
   * soon as it is accepted. */
  async function upload(files: File[]): Promise<void> {
    const refused: string[] = [];
    setError(null);
    for (const file of files) {
      setUploading((n) => n + 1);
      try {
        await uploadDocument(deps, base.kb_id, file, crypto.randomUUID());
        setTick((n) => n + 1);
      } catch (failure) {
        refused.push(`${displaySafe(file.name)}: ${uploadErrorText(failure)}`);
        setError(refused.join("\n"));
      } finally {
        setUploading((n) => n - 1);
      }
    }
  }

  async function remove(docId: string): Promise<void> {
    if (deleting.current) return;
    deleting.current = true;
    try {
      await deleteDocument(deps, docId);
      setError(null);
      drop(docId);
    } catch (failure) {
      setError(knowledgeErrorText(failure));
      // Already gone (another tab): it leaves the list too.
      if (failure instanceof ApiError && failure.code === "knowledge_document_not_found")
        drop(docId);
    } finally {
      deleting.current = false;
    }
  }

  function drop(docId: string): void {
    // The row and its buttons disappear: keep focus in the section.
    heading.current?.focus();
    setConfirming(null);
    setDocs((current) => current.filter((doc) => doc.doc_id !== docId));
    setTotal((n) => Math.max(0, n - 1));
  }

  const name = displaySafe(base.name);
  return (
    <section aria-labelledby="documents-heading" className="space-y-3">
      <h3
        id="documents-heading"
        ref={heading}
        tabIndex={-1}
        className="truncate text-sm font-semibold outline-none"
      >
        Documents in {name}
      </h3>
      <p className="flex gap-2 rounded-lg bg-muted px-3 py-2 text-sm">
        <Info aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
        {PROCESSING_TEXT[base.processing].detail}
      </p>
      <label
        className={cn(
          "flex cursor-pointer flex-col items-center gap-1 rounded-lg border border-dashed px-4 py-6 text-center text-sm focus-within:ring-[3px] focus-within:ring-ring/50",
          dragging && "border-primary bg-accent",
        )}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => {
          setDragging(false);
        }}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          void upload([...event.dataTransfer.files]);
        }}
      >
        <FileUp aria-hidden="true" className="size-5 text-muted-foreground" />
        <span className="font-medium">Drop files here, or choose files</span>
        <span className="text-xs text-muted-foreground">
          PDF, Word, Excel, PowerPoint, text or Markdown
        </span>
        <input
          type="file"
          multiple
          className="sr-only"
          accept=".pdf,.docx,.xlsx,.pptx,.txt,.md"
          onChange={(event) => {
            const files = [...(event.target.files ?? [])];
            event.target.value = "";
            void upload(files);
          }}
        />
      </label>
      <p role="status" className="text-sm text-muted-foreground empty:hidden">
        {uploading > 0 ? "Uploading…" : ""}
      </p>
      {error !== null && (
        <p role="alert" className="text-sm whitespace-pre-line text-destructive">
          {error}
        </p>
      )}
      <ul aria-label={`Documents in ${name}`} className="divide-y rounded-lg border empty:hidden">
        {docs.map((doc) => {
          const title = displaySafe(doc.title);
          return (
            <li key={doc.doc_id} className="px-4 py-3">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <p className="min-w-0 flex-1 truncate text-sm">{title}</p>
                <span className="text-xs text-muted-foreground">{size(doc.size_bytes)}</span>
                <Badge variant={doc.status === "failed" ? "destructive" : "secondary"}>
                  {STATUS[doc.status]}
                </Badge>
                {confirming === doc.doc_id ? (
                  <span className="flex gap-1">
                    <Button
                      type="button"
                      autoFocus
                      variant="destructive"
                      size="xs"
                      aria-label={`Confirm delete ${title}`}
                      onClick={() => {
                        void remove(doc.doc_id);
                      }}
                    >
                      Confirm delete
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="xs"
                      onClick={() => {
                        cancelled.current = doc.doc_id;
                        setConfirming(null);
                      }}
                    >
                      Cancel
                    </Button>
                  </span>
                ) : (
                  <Button
                    ref={(node) => {
                      if (node) trash.current.set(doc.doc_id, node);
                      else trash.current.delete(doc.doc_id);
                    }}
                    type="button"
                    variant="ghost"
                    size="xs"
                    aria-label={`Delete ${title}`}
                    className="hover:text-destructive"
                    onClick={() => {
                      setConfirming(doc.doc_id);
                    }}
                  >
                    <Trash2 />
                  </Button>
                )}
              </div>
              {doc.status === "failed" && (
                <p className="mt-1 text-xs text-destructive">
                  {documentFailureText(doc.error_code)}
                </p>
              )}
            </li>
          );
        })}
      </ul>
      {total > docs.length && (
        <p className="text-xs text-muted-foreground">
          Showing the first {String(docs.length)} of {String(total)} documents.
        </p>
      )}
    </section>
  );
}
