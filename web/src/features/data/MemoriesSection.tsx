import { useEffect, useState } from "react";

import { deleteMemory, listMemories, type DataDeps } from "./api";
import { dataErrorText } from "./messages";
import type { Memory } from "./parse";

function when(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "unknown date" : date.toLocaleString();
}

export function MemoriesSection({ deps }: { deps: DataDeps }) {
  const [memories, setMemories] = useState<Memory[]>([]);
  const [total, setTotal] = useState(0);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);

  /** Append the next page ("Load more"). The first page is loaded by the effect below. */
  async function loadMore(offset: number): Promise<void> {
    try {
      const page = await listMemories(deps, offset);
      setMemories((current) => [...current, ...page.memories]);
      setTotal(page.total);
      setError(null);
    } catch (failure) {
      setError(dataErrorText(failure));
    }
  }

  useEffect(() => {
    let current = true;
    listMemories(deps, 0).then(
      (page) => {
        if (!current) return;
        setMemories(page.memories);
        setTotal(page.total);
        setLoaded(true);
      },
      (failure: unknown) => {
        if (!current) return;
        setError(dataErrorText(failure));
        setLoaded(true);
      },
    );
    return () => {
      current = false;
    };
    // Load once when the section appears; `deps` is stable for the life of the page.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function remove(id: string): Promise<void> {
    setConfirming(null);
    try {
      await deleteMemory(deps, id);
      setMemories((current) => current.filter((memory) => memory.id !== id));
      setTotal((current) => Math.max(0, current - 1));
      setError(null);
    } catch (failure) {
      setError(dataErrorText(failure));
    }
  }

  return (
    <section aria-labelledby="memories-heading" className="mt-6">
      <h2 id="memories-heading" className="text-lg font-semibold">
        Memories
      </h2>
      <p className="text-sm opacity-80">
        What you asked the assistant to remember. Only you can see these.
      </p>
      {error !== null && (
        <p role="alert" className="mt-2">
          {error}
        </p>
      )}
      {!loaded && <p className="mt-2 opacity-70">Loading…</p>}
      {loaded && error === null && memories.length === 0 && (
        <p className="mt-2 opacity-70">No memories.</p>
      )}
      <ul className="mt-2 space-y-2">
        {memories.map((memory) => (
          <li key={memory.id} className="rounded border p-2">
            <p className="whitespace-pre-wrap break-words">{memory.text}</p>
            <p className="text-xs opacity-70">{when(memory.created_at)}</p>
            {confirming === memory.id ? (
              <div className="mt-1 flex gap-2">
                <button
                  type="button"
                  className="rounded border px-2 py-0.5"
                  onClick={() => void remove(memory.id)}
                >
                  Confirm delete
                </button>
                <button
                  type="button"
                  className="rounded border px-2 py-0.5"
                  onClick={() => {
                    setConfirming(null);
                  }}
                >
                  Cancel
                </button>
              </div>
            ) : (
              <button
                type="button"
                className="mt-1 rounded border px-2 py-0.5"
                onClick={() => {
                  setConfirming(memory.id);
                }}
              >
                Delete
              </button>
            )}
          </li>
        ))}
      </ul>
      {memories.length < total && (
        <button
          type="button"
          className="mt-2 rounded border px-3 py-1"
          onClick={() => void loadMore(memories.length)}
        >
          Load more
        </button>
      )}
    </section>
  );
}
