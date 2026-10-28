import { useEffect, useRef, useState, type SubmitEvent } from "react";

import { displaySafe } from "@/features/chat/displaySafe";
import { characterCount } from "@/features/chat/limits";
import { ApiError } from "@/lib/request";

import { deleteThread, listThreads, renameThread, type ThreadDeps } from "./api";
import { TITLE_MAX_CHARS, threadErrorText } from "./messages";
import type { ThreadSummary } from "./parse";

const SHOWN_TITLE_CHARS = 200;

function when(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "unknown date" : date.toLocaleString();
}

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
    <section aria-labelledby="threads-heading" className="mt-6">
      <h2 id="threads-heading" ref={heading} tabIndex={-1} className="text-lg font-semibold">
        Conversations
      </h2>
      {error !== null && (
        <p role="alert" className="mt-2">
          {error}
        </p>
      )}
      {!loaded && <p className="mt-2 opacity-70">Loading…</p>}
      {loaded && error === null && threads.length === 0 && (
        <p className="mt-2 opacity-70">No conversations yet.</p>
      )}
      <ul className="mt-2 space-y-2">
        {threads.map((thread) => (
          <li key={thread.thread_id} className="rounded border p-2">
            {renaming === thread.thread_id ? (
              <form
                onSubmit={(event: SubmitEvent) => {
                  event.preventDefault();
                  void saveRename(thread.thread_id);
                }}
                onKeyDown={(event) => {
                  if (event.key === "Escape") stopRename(thread.thread_id);
                }}
              >
                <label htmlFor={`title-${thread.thread_id}`} className="text-xs">
                  Conversation title
                </label>
                <input
                  id={`title-${thread.thread_id}`}
                  autoFocus
                  value={draft}
                  className="block w-full rounded border p-1"
                  aria-describedby={renameProblem === null ? undefined : "rename-problem"}
                  onChange={(event) => {
                    setDraft(event.target.value);
                    setRenameProblem(null);
                  }}
                />
                {renameProblem !== null && (
                  <p id="rename-problem" role="alert" className="mt-1">
                    {renameProblem}
                  </p>
                )}
                <div className="mt-1 flex gap-2">
                  <button type="submit" className="rounded border px-2 py-0.5">
                    Save
                  </button>
                  <button
                    type="button"
                    className="rounded border px-2 py-0.5"
                    onClick={() => {
                      stopRename(thread.thread_id);
                    }}
                  >
                    Cancel
                  </button>
                </div>
              </form>
            ) : (
              <>
                <p className="break-words font-medium">{shownTitle(thread.title)}</p>
                <p className="text-xs opacity-70">
                  {when(thread.updated_at)} · {thread.message_count}{" "}
                  {thread.message_count === 1 ? "message" : "messages"}
                </p>
                {confirming === thread.thread_id ? (
                  <div className="mt-1 flex flex-wrap gap-2">
                    <button
                      type="button"
                      autoFocus
                      className="rounded border px-2 py-0.5"
                      onClick={() => void remove(thread.thread_id)}
                    >
                      Confirm delete
                    </button>
                    <button
                      type="button"
                      className="rounded border px-2 py-0.5"
                      onClick={() => {
                        refocus.current = `${thread.thread_id}:delete`;
                        setConfirming(null);
                      }}
                    >
                      Cancel
                    </button>
                  </div>
                ) : (
                  <div className="mt-1 flex gap-2">
                    <button
                      type="button"
                      aria-label={`Open ${shownTitle(thread.title)}`}
                      aria-current={thread.thread_id === activeThreadId ? "true" : undefined}
                      disabled={openDisabled}
                      className="rounded border px-2 py-0.5"
                      onClick={() => {
                        onOpen(thread.thread_id);
                      }}
                    >
                      Open
                    </button>
                    <button
                      type="button"
                      ref={register(`${thread.thread_id}:rename`)}
                      aria-label={`Rename ${shownTitle(thread.title)}`}
                      className="rounded border px-2 py-0.5"
                      onClick={() => {
                        startRename(thread);
                      }}
                    >
                      Rename
                    </button>
                    <button
                      type="button"
                      ref={register(`${thread.thread_id}:delete`)}
                      aria-label={`Delete ${shownTitle(thread.title)}`}
                      className="rounded border px-2 py-0.5"
                      onClick={() => {
                        setRenaming(null);
                        setConfirming(thread.thread_id);
                      }}
                    >
                      Delete
                    </button>
                  </div>
                )}
              </>
            )}
          </li>
        ))}
      </ul>
      {threads.length < total && (
        <button
          type="button"
          className="mt-2 rounded border px-3 py-1"
          onClick={() => void loadMore()}
        >
          Load more
        </button>
      )}
    </section>
  );
}
