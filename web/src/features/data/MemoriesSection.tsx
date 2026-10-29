import { Brain, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

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
  const heading = useRef<HTMLHeadingElement>(null);
  const deleteButtons = useRef(new Map<string, HTMLButtonElement>());
  const refocus = useRef<string | null>(null);

  // Leaving the "Confirm delete" step removes the button that had focus: put focus back on
  // that memory's Delete button (or, once it is gone, on the section heading).
  useEffect(() => {
    if (confirming === null && refocus.current !== null) {
      deleteButtons.current.get(refocus.current)?.focus();
      refocus.current = null;
    }
  }, [confirming]);

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
    refocus.current = id;
    setConfirming(null);
    try {
      await deleteMemory(deps, id);
      // The memory (and its buttons) are about to disappear: keep focus in the section.
      heading.current?.focus();
      setMemories((current) => current.filter((memory) => memory.id !== id));
      setTotal((current) => Math.max(0, current - 1));
      setError(null);
    } catch (failure) {
      setError(dataErrorText(failure));
    }
  }

  return (
    <Card asSection aria-labelledby="memories-heading" className="gap-4">
      <CardHeader>
        <h2
          id="memories-heading"
          ref={heading}
          tabIndex={-1}
          className="flex items-center gap-2 font-semibold outline-none"
        >
          <Brain aria-hidden="true" className="size-4 text-muted-foreground" />
          Memories
        </h2>
        <CardDescription>
          What you asked the assistant to remember. Only you can see these.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {error !== null && (
          <p role="alert" className="mb-3 text-sm text-destructive">
            {error}
          </p>
        )}
        {!loaded && (
          <div className="space-y-2">
            <p className="sr-only">Loading…</p>
            <Skeleton className="h-14 w-full" />
            <Skeleton className="h-14 w-full" />
          </div>
        )}
        {loaded && error === null && memories.length === 0 && (
          <p className="rounded-lg border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">
            No memories.
          </p>
        )}
        <ul className="divide-y rounded-lg border empty:hidden">
          {memories.map((memory) => (
            <li key={memory.id} className="flex items-start gap-3 px-4 py-3">
              <div className="min-w-0 flex-1">
                <p className="text-sm break-words whitespace-pre-wrap">{memory.text}</p>
                <p className="mt-1 text-xs text-muted-foreground">{when(memory.created_at)}</p>
              </div>
              {confirming === memory.id ? (
                <div className="flex shrink-0 flex-wrap justify-end gap-1.5">
                  <Button
                    type="button"
                    autoFocus
                    variant="destructive"
                    size="xs"
                    onClick={() => void remove(memory.id)}
                  >
                    Confirm delete
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="xs"
                    onClick={() => {
                      refocus.current = memory.id;
                      setConfirming(null);
                    }}
                  >
                    Cancel
                  </Button>
                </div>
              ) : (
                <Button
                  type="button"
                  ref={(node) => {
                    if (node === null) deleteButtons.current.delete(memory.id);
                    else deleteButtons.current.set(memory.id, node);
                  }}
                  variant="ghost"
                  size="xs"
                  className="shrink-0 text-muted-foreground hover:text-destructive"
                  onClick={() => {
                    setConfirming(memory.id);
                  }}
                >
                  <Trash2 />
                  Delete
                </Button>
              )}
            </li>
          ))}
        </ul>
        {memories.length < total && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="mt-2 w-full text-muted-foreground"
            onClick={() => void loadMore(memories.length)}
          >
            Load more
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
