import { Check, Pencil, Trash2, X } from "lucide-react";
import { useEffect, useRef, useState, type SubmitEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { displaySafe } from "@/features/chat/displaySafe";
import { characterCount } from "@/features/chat/limits";
import { ApiError } from "@/lib/request";
import { cn } from "@/lib/utils";

import { deleteThread, listThreads, renameThread, type ThreadDeps } from "./api";
import { TITLE_MAX_CHARS, threadErrorText } from "./messages";
import type { ThreadSummary } from "./parse";

const SHOWN_TITLE_CHARS = 200;

/** Today's conversations show the time; older ones the date. */
function when(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "unknown date";
  return date.toDateString() === new Date().toDateString()
    ? date.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })
    : date.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/** Row actions stay out of the way until the row is hovered or focused (always shown on touch). */
const ROW_ACTION =
  "text-muted-foreground opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 focus-visible:opacity-100 [@media(hover:none)]:opacity-100";

/** A title is untrusted text: invisible and reordering characters are marked, and it is cut. */
export function shownTitle(title: string | null): string {
  if (title === null || title.trim() === "") return "Untitled conversation";
  const safe = displaySafe(title);
  return safe.length > SHOWN_TITLE_CHARS ? `${safe.slice(0, SHOWN_TITLE_CHARS)}…` : safe;
}

export interface ThreadListProps {
  deps: ThreadDeps;
  /** Changes whenever the list may be out of date (a reply finished); the first page reloads. */
  refresh: number;
  /** A conversation was deleted on the server: the chat must drop it if it is open. */
  onDeleted: (threadId: string) => void;
  /** Show this conversation in the chat and continue it. */
  onOpen: (threadId: string) => void;
  /** The conversation open in the chat, if it has a server-side thread. */
  activeThreadId: string | null;
  /** True while a reply is streaming or another conversation is loading. */
  openDisabled: boolean;
}

export function ThreadList({
  deps,
  refresh,
  onDeleted,
  onOpen,
  activeThreadId,
  openDisabled,
}: ThreadListProps) {
  const [threads, setThreads] = useState<ThreadSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [renameProblem, setRenameProblem] = useState<string | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const buttons = useRef(new Map<string, HTMLButtonElement>());
  const refocus = useRef<string | null>(null);
  const saving = useRef(false);
  const latest = useRef(0);

  // Leaving the rename form or the "Confirm delete" step removes the control that had focus:
  // put it back on that conversation's own button.
  useEffect(() => {
    if (confirming === null && renaming === null && refocus.current !== null) {
      buttons.current.get(refocus.current)?.focus();
      refocus.current = null;
    }
  }, [confirming, renaming]);

  useEffect(() => {
    const request = ++latest.current;
    let mounted = true;
    listThreads(deps, 0).then(
      (page) => {
        if (!mounted || request !== latest.current) return;
        setThreads(page.threads);
        setTotal(page.total);
        setError(null);
        setLoaded(true);
      },
      (failure: unknown) => {
        if (!mounted || request !== latest.current) return;
        setError(threadErrorText(failure, "list"));
        setLoaded(true);
      },
    );
    return () => {
      mounted = false;
    };
    // `deps` is stable for the life of the page; only a finished reply reloads the list.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refresh]);

  async function loadMore(): Promise<void> {
    const request = latest.current;
    try {
      const page = await listThreads(deps, threads.length);
      if (request !== latest.current) return;
      setThreads((current) => [
        ...current,
        ...page.threads.filter((next) => !current.some((c) => c.thread_id === next.thread_id)),
      ]);
      setTotal(page.total);
      setError(null);
    } catch (failure) {
      if (request === latest.current) setError(threadErrorText(failure, "list"));
    }
  }

  function startRename(thread: ThreadSummary): void {
    setConfirming(null);
    setRenaming(thread.thread_id);
    setDraft(thread.title ?? "");
    setRenameProblem(null);
  }

  function stopRename(id: string): void {
    refocus.current = `${id}:rename`;
    setRenaming(null);
    setRenameProblem(null);
  }

  async function saveRename(id: string): Promise<void> {
    const title = draft.trim();
    if (title === "" || characterCount(title) > TITLE_MAX_CHARS) {
      setRenameProblem(`Use 1 to ${String(TITLE_MAX_CHARS)} characters.`);
      return;
    }
    if (saving.current) return; // a second Enter or click while the first is in flight
    saving.current = true;
    try {
      const stored = await renameThread(deps, id, title);
      setThreads((current) =>
        current.map((thread) => (thread.thread_id === id ? { ...thread, title: stored } : thread)),
      );
      setError(null);
      stopRename(id);
    } catch (failure) {
      setRenameProblem(threadErrorText(failure, "rename"));
    } finally {
      saving.current = false;
    }
  }

  async function remove(id: string): Promise<void> {
    refocus.current = `${id}:delete`;
    setConfirming(null);
    try {
      await deleteThread(deps, id);
    } catch (failure) {
      setError(threadErrorText(failure, "delete"));
      // Gone already (another tab, or retention): the list entry is stale, so drop it.
      if (failure instanceof ApiError && failure.kind === "not_found") {
        setThreads((current) => current.filter((thread) => thread.thread_id !== id));
        onDeleted(id);
      }
      return;
    }
    // The conversation (and its buttons) are about to disappear: keep focus in the section.
    heading.current?.focus();
    setThreads((current) => current.filter((thread) => thread.thread_id !== id));
    setTotal((current) => Math.max(0, current - 1));
    setError(null);
    onDeleted(id);
  }

  const register = (key: string) => (node: HTMLButtonElement | null) => {
    if (node === null) buttons.current.delete(key);
    else buttons.current.set(key, node);
  };

  return (
    <section aria-labelledby="threads-heading" className="mt-2">
      <h2
        id="threads-heading"
        ref={heading}
        tabIndex={-1}
        className="px-2.5 pt-2 pb-1.5 text-xs font-medium text-muted-foreground outline-none"
      >
        Conversations
      </h2>
      {error !== null && (
        <p role="alert" className="mx-2.5 my-1 text-xs text-destructive">
          {error}
        </p>
      )}
      {!loaded && (
        <div className="space-y-1 px-2.5 py-1">
          <p className="sr-only">Loading…</p>
          {[0, 1, 2].map((row) => (
            <div key={row} className="space-y-1.5 py-1.5">
              <Skeleton className="h-3.5 w-4/5" />
              <Skeleton className="h-2.5 w-1/3" />
            </div>
          ))}
        </div>
      )}
      {loaded && error === null && threads.length === 0 && (
        <p className="px-2.5 py-1 text-sm text-muted-foreground">No conversations yet.</p>
      )}
      <ul className="space-y-0.5">
        {threads.map((thread) => {
          const active = thread.thread_id === activeThreadId;
          return (
            <li
              key={thread.thread_id}
              className={cn(
                "group relative rounded-md transition-colors hover:bg-sidebar-accent",
                active && "bg-sidebar-accent",
              )}
            >
              {renaming === thread.thread_id ? (
                <form
                  className="p-1.5"
                  onSubmit={(event: SubmitEvent) => {
                    event.preventDefault();
                    void saveRename(thread.thread_id);
                  }}
                  onKeyDown={(event) => {
                    if (event.key === "Escape") stopRename(thread.thread_id);
                  }}
                >
                  <label htmlFor={`title-${thread.thread_id}`} className="sr-only">
                    Conversation title
                  </label>
                  <div className="flex items-center gap-1">
                    <Input
                      id={`title-${thread.thread_id}`}
                      autoFocus
                      value={draft}
                      className="h-8 bg-background"
                      aria-invalid={renameProblem !== null || undefined}
                      aria-describedby={renameProblem === null ? undefined : "rename-problem"}
                      onChange={(event) => {
                        setDraft(event.target.value);
                        setRenameProblem(null);
                      }}
                    />
                    <Button type="submit" variant="ghost" size="icon-xs" aria-label="Save">
                      <Check />
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon-xs"
                      aria-label="Cancel"
                      onClick={() => {
                        stopRename(thread.thread_id);
                      }}
                    >
                      <X />
                    </Button>
                  </div>
                  {renameProblem !== null && (
                    <p id="rename-problem" role="alert" className="mt-1 text-xs text-destructive">
                      {renameProblem}
                    </p>
                  )}
                </form>
              ) : (
                <>
                  <button
                    type="button"
                    aria-label={`Open ${shownTitle(thread.title)}`}
                    aria-current={active ? "true" : undefined}
                    disabled={openDisabled}
                    className="block w-full rounded-md py-2 pr-16 pl-2.5 text-left outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:cursor-not-allowed"
                    onClick={() => {
                      onOpen(thread.thread_id);
                    }}
                  >
                    <p className="truncate text-sm font-medium">{shownTitle(thread.title)}</p>
                    <p className="mt-0.5 truncate text-xs text-muted-foreground">
                      {when(thread.updated_at)} · {thread.message_count}{" "}
                      {thread.message_count === 1 ? "message" : "messages"}
                    </p>
                  </button>
                  {confirming === thread.thread_id ? (
                    <div className="flex flex-wrap items-center gap-1.5 px-2.5 pb-2">
                      <Button
                        type="button"
                        autoFocus
                        variant="destructive"
                        size="xs"
                        onClick={() => void remove(thread.thread_id)}
                      >
                        Confirm delete
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        size="xs"
                        onClick={() => {
                          refocus.current = `${thread.thread_id}:delete`;
                          setConfirming(null);
                        }}
                      >
                        Cancel
                      </Button>
                    </div>
                  ) : (
                    <div className="absolute top-1.5 right-1.5 flex gap-0.5">
                      <Button
                        type="button"
                        ref={register(`${thread.thread_id}:rename`)}
                        aria-label={`Rename ${shownTitle(thread.title)}`}
                        title="Rename"
                        variant="ghost"
                        size="icon-xs"
                        className={ROW_ACTION}
                        onClick={() => {
                          startRename(thread);
                        }}
                      >
                        <Pencil />
                      </Button>
                      <Button
                        type="button"
                        ref={register(`${thread.thread_id}:delete`)}
                        aria-label={`Delete ${shownTitle(thread.title)}`}
                        title="Delete"
                        variant="ghost"
                        size="icon-xs"
                        className={cn(ROW_ACTION, "hover:text-destructive")}
                        onClick={() => {
                          setRenaming(null);
                          setConfirming(thread.thread_id);
                        }}
                      >
                        <Trash2 />
                      </Button>
                    </div>
                  )}
                </>
              )}
            </li>
          );
        })}
      </ul>
      {threads.length < total && (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="mt-1 w-full text-muted-foreground"
          onClick={() => void loadMore()}
        >
          Load more
        </Button>
      )}
    </section>
  );
}
