import {
  Download,
  FileText,
  FileUp,
  Globe,
  Info,
  Loader2,
  MoreHorizontal,
  Search,
  Trash2,
  Upload,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { displaySafe } from "@/features/chat/displaySafe";
import type { DataDeps } from "@/features/data/api";
import { ApiError } from "@/lib/request";
import { cn } from "@/lib/utils";

import {
  addWebPage,
  deleteDocument,
  downloadDocument,
  listDocuments,
  uploadDocument,
  type DocumentSort,
  type StatusFilter,
} from "./api";
import { ConfirmDialog, SELECT } from "./BaseDialogs";
import {
  documentKind,
  downloadName,
  formatDate,
  formatDateTime,
  formatSize,
  plural,
} from "./format";
import {
  documentFailureText,
  knowledgeErrorText,
  PROCESSING_TEXT,
  uploadErrorText,
} from "./messages";
import type { DocumentStatus, KnowledgeBase, KnowledgeDocument } from "./parse";

export const POLL_MS = 2000;
const POLL_MAX_MS = 15_000;

/**
 * The wait before poll `n` (0 first): 2 s, then half as long again each time, up to 15 s. A
 * large file can take minutes to ingest, and every poll counts against the user's rate limit
 * (60 a minute by default), which the chat shares.
 */
export function pollDelay(n: number): number {
  return Math.min(POLL_MS * 1.5 ** n, POLL_MAX_MS);
}
/** A file refused as busy (the user's ingestion cap, or this process's upload cap) is sent again
 * after the server's Retry-After (or this long, in seconds), at most this many times. */
const BUSY_DEFAULT_SECONDS = 5;
const BUSY_MAX_SECONDS = 30;
const BUSY_ATTEMPTS = 10;
const isBusy = (failure: unknown): failure is ApiError =>
  failure instanceof ApiError &&
  failure.kind === "rate_limited" &&
  (failure.code === "ingestion_concurrency_exceeded" || failure.code === "upload_busy");

/** The server's largest page; "Show more" adds one. */
export const PAGE = 100;
/** Typing in the search box waits this long before asking the server. */
const SEARCH_MS = 300;
const ACCEPT = ".pdf,.docx,.xlsx,.csv,.pptx,.txt,.md";
const STATUS: Record<DocumentStatus, string> = {
  queued: "Queued",
  parsing: "Reading",
  embedding: "Indexing",
  ready: "Ready",
  failed: "Failed",
};
const SORTS: Record<DocumentSort, string> = {
  oldest: "Oldest first",
  newest: "Newest first",
  name: "Name",
  updated: "Recently updated",
  size: "Largest first",
};
const FILTERS: Record<StatusFilter, string> = {
  ready: "Ready",
  processing: "Processing",
  failed: "Failed",
};
const settled = (doc: KnowledgeDocument) => doc.status === "ready" || doc.status === "failed";

/** Give the browser a downloaded file and forget it; the object URL is revoked after the click. */
function save(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.rel = "noopener";
  link.style.display = "none";
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => {
    URL.revokeObjectURL(url);
  }, 0);
}

function StatusBadge({ status }: { status: DocumentStatus }) {
  if (status === "failed") return <Badge variant="destructive">{STATUS.failed}</Badge>;
  if (status === "ready") return <Badge variant="secondary">{STATUS.ready}</Badge>;
  return (
    <Badge variant="outline" className="text-muted-foreground">
      <Loader2 aria-hidden="true" className="animate-spin motion-reduce:animate-none" />
      {STATUS[status]}
    </Badge>
  );
}

/**
 * One base's documents: find, sort and filter them, upload by drop or picker, add web pages,
 * download or delete one or many, and each one's status kept up to date while it is processed.
 */
export function DocumentsPanel({
  deps,
  base,
  onTotal,
}: {
  deps: DataDeps;
  base: KnowledgeBase;
  /** The base's document count, whenever an unfiltered load says it. */
  onTotal?: (total: number) => void;
}) {
  const [docs, setDocs] = useState<KnowledgeDocument[]>([]);
  const [total, setTotal] = useState(0);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [uploading, setUploading] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [tick, setTick] = useState(0);
  // Counts finished loads, failed ones too, so polling goes on after a failed refresh.
  const [loads, setLoads] = useState(0);
  const [pages, setPages] = useState(1);
  const [draft, setDraft] = useState("");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<StatusFilter | "all">("all");
  const [sort, setSort] = useState<DocumentSort>("oldest");
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const [confirming, setConfirming] = useState<KnowledgeDocument[] | null>(null);
  const [addingPage, setAddingPage] = useState(false);
  const heading = useRef<HTMLHeadingElement>(null);
  const picker = useRef<HTMLInputElement>(null);
  // Polls since the last upload; each one waits longer (`pollDelay`).
  const polls = useRef(0);
  const pending = docs.some((doc) => !settled(doc));
  const filtered = search !== "" || status !== "all";
  // A read-only grant (RAG-09.03): the server would refuse an upload or a delete.
  const canWrite = base.access !== "read";
  const name = displaySafe(base.name);

  /** A new search, filter or order starts again from the first page, with nothing selected. */
  function restart(): void {
    setPages(1);
    setSelected(new Set());
  }

  // The search box asks the server once the user pauses typing.
  useEffect(() => {
    const timer = setTimeout(() => {
      const next = draft.trim();
      if (next === search) return;
      setSearch(next);
      restart();
    }, SEARCH_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [draft, search]);

  useEffect(() => {
    const run = { live: true };
    const query = { search, sort, ...(status === "all" ? {} : { status }) };
    // Every page shown is loaded again, so a refresh keeps the rows the user has opened.
    void (async () => {
      try {
        const found: KnowledgeDocument[] = [];
        let count = 0;
        for (let page = 0; page < pages; page++) {
          const result = await listDocuments(deps, base.kb_id, page * PAGE, PAGE, query);
          found.push(...result.documents);
          count = result.total;
          if (found.length >= count) break;
        }
        if (!run.live) return;
        setDocs(found);
        setTotal(count);
        if (!filtered) onTotal?.(count);
        // A row that has gone (deleted elsewhere, or filtered out) is no longer selected.
        setSelected((current) => {
          const ids = new Set(found.map((doc) => doc.doc_id));
          return new Set([...current].filter((id) => ids.has(id)));
        });
      } catch (failure) {
        if (run.live) setError(knowledgeErrorText(failure));
      } finally {
        if (run.live) {
          setLoaded(true);
          setLoads((n) => n + 1);
        }
      }
    })();
    return () => {
      run.live = false;
    };
    // `deps` is stable for the life of the page; `onTotal` only reports.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [base.kb_id, tick, pages, search, status, sort]);

  // While a document is still being processed, look again after a short wait.
  useEffect(() => {
    if (!pending) return;
    const timer = setTimeout(() => {
      setTick((n) => n + 1);
    }, pollDelay(polls.current++));
    return () => {
      clearTimeout(timer);
    };
  }, [pending, loads]);

  /** Each file in turn; every refusal in the batch stays shown, and each upload is listed as
   * soon as it is accepted. A file refused only because too many documents are still being
   * processed waits and is sent again (same key), so a batch past that cap is not lost. */
  async function upload(files: File[]): Promise<void> {
    const refused: string[] = [];
    let accepted = 0;
    setError(null);
    setNotice("");
    for (const file of files) {
      setUploading((n) => n + 1);
      const key = crypto.randomUUID();
      try {
        for (let attempt = 1; ; attempt++) {
          try {
            await uploadDocument(deps, base.kb_id, file, key);
            break;
          } catch (failure) {
            if (!(isBusy(failure) && attempt < BUSY_ATTEMPTS)) throw failure;
            const wait = failure.retryAfterSeconds ?? BUSY_DEFAULT_SECONDS;
            await new Promise((resolve) =>
              setTimeout(resolve, Math.min(wait, BUSY_MAX_SECONDS) * 1000),
            );
          }
        }
        accepted++;
        polls.current = 0;
        setTick((n) => n + 1);
      } catch (failure) {
        refused.push(`${displaySafe(file.name)}: ${uploadErrorText(failure)}`);
        setError(refused.join("\n"));
      } finally {
        setUploading((n) => n - 1);
      }
    }
    if (accepted > 0) setNotice(`Added ${plural(accepted, "file")}. Processing has started.`);
  }

  async function addPage(url: string): Promise<string | null> {
    setNotice("");
    setUploading((n) => n + 1);
    try {
      await addWebPage(deps, base.kb_id, url, crypto.randomUUID());
      polls.current = 0;
      setTick((n) => n + 1);
      setNotice("Added the web page. It is fetched and processed shortly.");
      return null;
    } catch (failure) {
      return `${displaySafe(url)}: ${uploadErrorText(failure)}`;
    } finally {
      setUploading((n) => n - 1);
    }
  }

  async function download(doc: KnowledgeDocument): Promise<void> {
    try {
      save(await downloadDocument(deps, doc.doc_id), downloadName(doc.title));
    } catch (failure) {
      setError(knowledgeErrorText(failure));
    }
  }

  /** Delete each in turn; one that is already gone (another tab) leaves the list too. */
  async function remove(targets: KnowledgeDocument[]): Promise<string | null> {
    const gone = new Set<string>();
    let failed: unknown = null;
    for (const doc of targets) {
      try {
        await deleteDocument(deps, doc.doc_id);
        gone.add(doc.doc_id);
      } catch (failure) {
        if (failure instanceof ApiError && failure.code === "knowledge_document_not_found")
          gone.add(doc.doc_id);
        failed ??= failure;
      }
    }
    if (gone.size > 0) {
      setDocs((current) => current.filter((doc) => !gone.has(doc.doc_id)));
      setTotal((n) => {
        const left = Math.max(0, n - gone.size);
        if (!filtered) onTotal?.(left);
        return left;
      });
      setSelected((current) => new Set([...current].filter((id) => !gone.has(id))));
      setNotice(`Deleted ${plural(gone.size, "document")}.`);
    }
    if (failed === null) return null;
    const text = knowledgeErrorText(failed);
    // The dialog closes on success only: say what failed here too, once it has closed.
    if (gone.size > 0) setError(text);
    return gone.size > 0 ? null : text;
  }

  function toggle(docId: string): void {
    setSelected((current) => {
      const next = new Set(current);
      if (!next.delete(docId)) next.add(docId);
      return next;
    });
  }

  const all = docs.length > 0 && docs.every((doc) => selected.has(doc.doc_id));
  const chosen = docs.filter((doc) => selected.has(doc.doc_id));

  return (
    <section
      aria-labelledby="documents-heading"
      className={cn("relative space-y-4 rounded-xl", dragging && "ring-2 ring-foreground/30")}
      onDragOver={(event) => {
        if (!canWrite || !event.dataTransfer.types.includes("Files")) return;
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false);
      }}
      onDrop={(event) => {
        if (!canWrite) return;
        event.preventDefault();
        setDragging(false);
        void upload([...event.dataTransfer.files]);
      }}
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-baseline gap-2">
          <h2
            id="documents-heading"
            ref={heading}
            tabIndex={-1}
            className="text-sm font-semibold outline-none"
          >
            Documents in {name}
          </h2>
          {loaded && (
            <span className="text-sm text-muted-foreground">
              {filtered ? `${String(total)} found` : String(total)}
            </span>
          )}
        </div>
        {canWrite && (
          <div className="flex gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => {
                setAddingPage(true);
              }}
            >
              <Globe />
              Add web page
            </Button>
            <Button
              type="button"
              size="sm"
              onClick={() => {
                picker.current?.click();
              }}
            >
              <Upload />
              Upload files
            </Button>
          </div>
        )}
      </div>
      {canWrite && (
        <input
          ref={picker}
          type="file"
          multiple
          tabIndex={-1}
          aria-label="Upload files"
          className="sr-only"
          accept={ACCEPT}
          onChange={(event) => {
            const files = [...(event.target.files ?? [])];
            event.target.value = "";
            void upload(files);
          }}
        />
      )}

      <p className="flex gap-2 text-xs text-muted-foreground">
        <Info aria-hidden="true" className="mt-px size-3.5 shrink-0" />
        {PROCESSING_TEXT[base.processing].detail}
      </p>
      {!canWrite && (
        <p className="rounded-lg bg-muted px-3 py-2 text-sm">
          This knowledge base is shared with you to read. You can&apos;t add or delete its
          documents.
        </p>
      )}

      <p role="status" className="text-sm text-muted-foreground empty:hidden">
        {uploading > 0 ? "Adding…" : notice}
      </p>
      {error !== null && (
        <p
          role="alert"
          className="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm whitespace-pre-line text-destructive"
        >
          {error}
        </p>
      )}

      {(total > 0 || filtered) && (
        <div className="flex flex-wrap items-center gap-2">
          <label className="relative w-full sm:w-auto sm:min-w-48 sm:flex-1">
            <span className="sr-only">Search documents</span>
            <Search
              aria-hidden="true"
              className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground"
            />
            <Input
              type="search"
              value={draft}
              placeholder="Search by name"
              className="pl-8"
              onChange={(event) => {
                setDraft(event.target.value);
              }}
            />
          </label>
          <select
            aria-label="Status"
            className={SELECT}
            value={status}
            onChange={(event) => {
              setStatus(event.target.value as StatusFilter | "all");
              restart();
            }}
          >
            <option value="all">All statuses</option>
            {(Object.keys(FILTERS) as StatusFilter[]).map((key) => (
              <option key={key} value={key}>
                {FILTERS[key]}
              </option>
            ))}
          </select>
          <select
            aria-label="Sort by"
            className={SELECT}
            value={sort}
            onChange={(event) => {
              setSort(event.target.value as DocumentSort);
              restart();
            }}
          >
            {(Object.keys(SORTS) as DocumentSort[]).map((key) => (
              <option key={key} value={key}>
                {SORTS[key]}
              </option>
            ))}
          </select>
        </div>
      )}

      {!loaded && (
        <div className="space-y-2">
          <p className="sr-only">Loading…</p>
          <Skeleton className="h-14 w-full" />
          <Skeleton className="h-14 w-full" />
        </div>
      )}

      {loaded && total === 0 && !filtered && canWrite && (
        <label className="flex cursor-pointer flex-col items-center gap-2 rounded-xl border border-dashed px-6 py-12 text-center text-sm transition-colors focus-within:ring-[3px] focus-within:ring-ring/50 hover:bg-accent/40">
          <span className="flex size-11 items-center justify-center rounded-full bg-muted">
            <FileUp aria-hidden="true" className="size-5 text-muted-foreground" />
          </span>
          <span className="font-medium">Drop files here, or choose files</span>
          <span className="text-xs text-muted-foreground">
            PDF, Word, Excel, PowerPoint, CSV, text or Markdown
          </span>
          <input
            type="file"
            multiple
            className="sr-only"
            accept={ACCEPT}
            onChange={(event) => {
              const files = [...(event.target.files ?? [])];
              event.target.value = "";
              void upload(files);
            }}
          />
        </label>
      )}
      {loaded && total === 0 && !filtered && !canWrite && (
        <p className="rounded-xl border border-dashed px-6 py-10 text-center text-sm text-muted-foreground">
          No documents yet.
        </p>
      )}
      {loaded && total === 0 && filtered && (
        <div className="flex flex-col items-center gap-1 rounded-xl border border-dashed px-6 py-10 text-center text-sm">
          <p className="font-medium">No documents match</p>
          <Button
            type="button"
            variant="link"
            size="sm"
            onClick={() => {
              setDraft("");
              setSearch("");
              setStatus("all");
              restart();
            }}
          >
            Clear search and filters
          </Button>
        </div>
      )}

      {docs.length > 0 && (
        <div className="overflow-hidden rounded-xl border">
          {canWrite && (
            <div className="flex min-h-11 items-center gap-3 border-b bg-muted/40 px-4 py-1.5 text-xs text-muted-foreground">
              <input
                type="checkbox"
                aria-label="Select all shown documents"
                className="size-4 accent-foreground"
                checked={all}
                ref={(node) => {
                  if (node) node.indeterminate = selected.size > 0 && !all;
                }}
                onChange={() => {
                  setSelected(all ? new Set() : new Set(docs.map((doc) => doc.doc_id)));
                }}
              />
              {selected.size > 0 ? (
                <>
                  <span className="font-medium text-foreground">
                    {String(selected.size)} selected
                  </span>
                  <Button
                    type="button"
                    variant="ghost"
                    size="xs"
                    className="text-destructive hover:bg-destructive/10 hover:text-destructive"
                    onClick={() => {
                      setConfirming(chosen);
                    }}
                  >
                    <Trash2 />
                    Delete
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="xs"
                    onClick={() => {
                      setSelected(new Set());
                    }}
                  >
                    Clear selection
                  </Button>
                </>
              ) : (
                <span>Select documents to delete several at once</span>
              )}
            </div>
          )}
          <ul aria-label={`Documents in ${name}`} className="divide-y">
            {docs.map((doc) => {
              const title = displaySafe(doc.title);
              const Icon = doc.source_url === null ? FileText : Globe;
              return (
                <li
                  key={doc.doc_id}
                  className={cn(
                    "flex items-start gap-3 px-4 py-3 transition-colors",
                    selected.has(doc.doc_id) && "bg-accent/50",
                  )}
                >
                  {canWrite && (
                    <input
                      type="checkbox"
                      aria-label={`Select ${title}`}
                      className="mt-2.5 size-4 shrink-0 accent-foreground"
                      checked={selected.has(doc.doc_id)}
                      onChange={() => {
                        toggle(doc.doc_id);
                      }}
                    />
                  )}
                  <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg bg-muted">
                    <Icon aria-hidden="true" className="size-4 text-muted-foreground" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium" title={title}>
                      {title}
                    </p>
                    <p className="flex flex-wrap gap-x-1.5 text-xs text-muted-foreground">
                      <span>{documentKind(doc)}</span>
                      {/* A web page has no size until it is fetched. */}
                      {doc.size_bytes > 0 && (
                        <>
                          <span aria-hidden="true">·</span>
                          <span>{formatSize(doc.size_bytes)}</span>
                        </>
                      )}
                      <span aria-hidden="true">·</span>
                      <span>
                        Added{" "}
                        <time dateTime={doc.created_at} title={formatDateTime(doc.created_at)}>
                          {formatDate(doc.created_at)}
                        </time>
                      </span>
                    </p>
                    {doc.source_url !== null && (
                      <p className="truncate text-xs text-muted-foreground">
                        {displaySafe(doc.source_url)}
                      </p>
                    )}
                    {doc.status === "failed" && (
                      <p className="mt-1 text-xs text-destructive">
                        {documentFailureText(doc.error_code)}
                      </p>
                    )}
                  </div>
                  <span className="mt-1.5 shrink-0">
                    <StatusBadge status={doc.status} />
                  </span>
                  <DropdownMenu modal={false}>
                    <DropdownMenuTrigger asChild>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon-sm"
                        aria-label={`Actions for ${title}`}
                        className="shrink-0 text-muted-foreground"
                      >
                        <MoreHorizontal />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem
                        disabled={doc.size_bytes === 0}
                        onSelect={() => {
                          void download(doc);
                        }}
                      >
                        <Download />
                        Download
                      </DropdownMenuItem>
                      {canWrite && (
                        <>
                          <DropdownMenuSeparator />
                          <DropdownMenuItem
                            destructive
                            onSelect={() => {
                              setConfirming([doc]);
                            }}
                          >
                            <Trash2 />
                            Delete
                          </DropdownMenuItem>
                        </>
                      )}
                    </DropdownMenuContent>
                  </DropdownMenu>
                </li>
              );
            })}
          </ul>
        </div>
      )}
      {total > docs.length && (
        <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
          <span>
            Showing {String(docs.length)} of {String(total)}
          </span>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              setPages((n) => n + 1);
            }}
          >
            Show more
          </Button>
        </div>
      )}

      {confirming !== null && (
        <ConfirmDialog
          open
          onOpenChange={(open) => {
            if (!open) setConfirming(null);
          }}
          title={
            confirming.length === 1
              ? `Delete ${displaySafe(confirming[0]?.title ?? "")}?`
              : `Delete ${plural(confirming.length, "document")}?`
          }
          confirmLabel="Delete"
          onConfirm={() => remove(confirming)}
          onCloseAutoFocus={(event) => {
            // The rows that opened it may be gone: keep focus in the panel.
            event.preventDefault();
            heading.current?.focus();
          }}
        >
          The assistant can no longer answer from {confirming.length === 1 ? "it" : "them"}. This
          can&apos;t be undone.
        </ConfirmDialog>
      )}
      <AddPageDialog open={addingPage} onOpenChange={setAddingPage} onAdd={addPage} />
    </section>
  );
}

/** A public `https` web page, fetched once by the server (RAG-10.02). */
function AddPageDialog({
  open,
  onOpenChange,
  onAdd,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onAdd: (url: string) => Promise<string | null>;
}) {
  const [url, setUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) setError(null);
        onOpenChange(next);
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add a web page</DialogTitle>
          <DialogDescription>
            A public https page. Its text is fetched once and added like a file.
          </DialogDescription>
        </DialogHeader>
        <form
          aria-label="Add a web page"
          className="space-y-5"
          onSubmit={(event) => {
            event.preventDefault();
            if (busy || url.trim() === "") return;
            setBusy(true);
            void onAdd(url.trim()).then((refused) => {
              setBusy(false);
              setError(refused);
              if (refused === null) {
                setUrl("");
                onOpenChange(false);
              }
            });
          }}
        >
          <div className="space-y-1.5">
            <label className="block text-sm font-medium" htmlFor="page-url">
              Web page address
            </label>
            <Input
              id="page-url"
              name="url"
              type="url"
              required
              autoFocus
              maxLength={2048}
              placeholder="https://"
              value={url}
              aria-invalid={error !== null}
              onChange={(event) => {
                setUrl(event.target.value);
              }}
            />
          </div>
          {error !== null && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                onOpenChange(false);
              }}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={busy}>
              {busy ? "Adding…" : "Add page"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
