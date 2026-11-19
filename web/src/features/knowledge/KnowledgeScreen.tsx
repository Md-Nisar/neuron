import { LayoutGrid, Library, List, Plus, Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { displaySafe } from "@/features/chat/displaySafe";
import type { DataDeps } from "@/features/data/api";
import { ApiError } from "@/lib/request";
import { cn } from "@/lib/utils";

import { createBase, deleteBase, listBases, renameBase } from "./api";
import { BaseDetail } from "./BaseDetail";
import {
  ConfirmDialog,
  CreateBaseDialog,
  RenameBaseDialog,
  SELECT,
  type Attempt,
} from "./BaseDialogs";
import { BaseList, type BaseActions, type Layout } from "./BaseList";
import { plural } from "./format";
import { knowledgeErrorText } from "./messages";
import type { KnowledgeBase, Language, Processing } from "./parse";

/** Without a Retry-After, a passing refusal of the list is tried again after this, this often. */
const RETRY_SECONDS = 5;
const RETRIES = 3;

type Owner = "all" | "mine" | "shared";
type BaseSort = "newest" | "oldest" | "name";
const LAYOUT_KEY = "neuron.knowledge.layout";

function savedLayout(): Layout {
  try {
    return localStorage.getItem(LAYOUT_KEY) === "list" ? "list" : "grid";
  } catch {
    return "grid";
  }
}

const SORTS: Record<
  BaseSort,
  { label: string; compare: (a: KnowledgeBase, b: KnowledgeBase) => number }
> = {
  newest: { label: "Newest first", compare: (a, b) => b.created_at.localeCompare(a.created_at) },
  oldest: { label: "Oldest first", compare: (a, b) => a.created_at.localeCompare(b.created_at) },
  name: {
    label: "Name",
    compare: (a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }),
  },
};

/** The user's knowledge bases (RAG-06.01): an index of them, and one base's own page. */
export function KnowledgeScreen({ deps }: { deps: DataDeps }) {
  const [bases, setBases] = useState<KnowledgeBase[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [retries, setRetries] = useState(0);
  const [search, setSearch] = useState("");
  const [owner, setOwner] = useState<Owner>("all");
  const [sort, setSort] = useState<BaseSort>("newest");
  const [layout, setLayout] = useState<Layout>(savedLayout);
  const [creating, setCreating] = useState(false);
  const [renaming, setRenaming] = useState<KnowledgeBase | null>(null);
  const [deleting, setDeleting] = useState<KnowledgeBase | null>(null);
  const [notice, setNotice] = useState("");
  const heading = useRef<HTMLHeadingElement>(null);
  // After a delete the control that opened the dialog is gone: focus goes to the heading.
  const toHeading = useRef(false);

  useEffect(() => {
    let mounted = true;
    let retry: ReturnType<typeof setTimeout> | undefined;
    listBases(deps).then(
      (found) => {
        if (!mounted) return;
        setBases(found);
        if (retries > 0) setError(null);
        setLoaded(true);
      },
      (failure: unknown) => {
        if (!mounted) return;
        setError(knowledgeErrorText(failure));
        setLoaded(true);
        // A passing refusal (rate limit, a restart) is tried again after the server's
        // Retry-After, or the list would stay empty until the page is reloaded (UX-01).
        if (
          failure instanceof ApiError &&
          (failure.kind === "rate_limited" || failure.kind === "unavailable") &&
          retries < RETRIES
        )
          retry = setTimeout(
            () => {
              setRetries((n) => n + 1);
            },
            Math.max(1, failure.retryAfterSeconds ?? RETRY_SECONDS) * 1000,
          );
      },
    );
    return () => {
      mounted = false;
      clearTimeout(retry);
    };
    // Load when the screen appears, and again for each retry; `deps` is stable for the page.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [retries]);

  function chooseLayout(next: Layout): void {
    setLayout(next);
    try {
      localStorage.setItem(LAYOUT_KEY, next);
    } catch {
      // Private mode or blocked storage: the choice lasts for this visit only.
    }
  }

  /** Make a change; resolves with why it was refused, or null. A base already gone leaves. */
  async function run(action: () => Promise<void>, kbId?: string): Attempt {
    try {
      await action();
      setError(null);
      return null;
    } catch (failure) {
      if (failure instanceof ApiError && failure.code === "knowledge_base_not_found") {
        setBases((current) => current.filter((b) => b.kb_id !== kbId));
        if (openId === kbId) setOpenId(null);
      }
      return knowledgeErrorText(failure);
    }
  }

  const create = (name: string, processing: Processing, language: Language): Attempt =>
    run(async () => {
      const made = await createBase(deps, name, processing, language);
      setBases((current) => [...current, { ...made, document_count: 0 }]);
      setNotice(`Created ${displaySafe(made.name)}.`);
      setOpenId(made.kb_id);
    });

  const rename = (base: KnowledgeBase, name: string): Attempt =>
    run(async () => {
      const stored = await renameBase(deps, base.kb_id, name);
      setBases((current) =>
        current.map((b) =>
          b.kb_id === base.kb_id ? { ...stored, document_count: b.document_count } : b,
        ),
      );
      setNotice(`Renamed to ${displaySafe(stored.name)}.`);
    }, base.kb_id);

  const remove = (base: KnowledgeBase): Attempt =>
    run(async () => {
      await deleteBase(deps, base.kb_id);
      toHeading.current = true;
      setOpenId(null);
      setBases((current) => current.filter((b) => b.kb_id !== base.kb_id));
      setNotice(`Deleted ${displaySafe(base.name)}.`);
    }, base.kb_id);

  const actions: BaseActions = {
    onOpen: (base) => {
      setNotice("");
      setOpenId(base.kb_id);
    },
    onRename: setRenaming,
    onDelete: setDeleting,
  };

  const shared = bases.some((base) => base.access !== "owner");
  const shown = useMemo(() => {
    const words = search.trim().toLocaleLowerCase();
    return bases
      .filter((base) => words === "" || base.name.toLocaleLowerCase().includes(words))
      .filter(
        (base) =>
          owner === "all" || (owner === "mine" ? base.access === "owner" : base.access !== "owner"),
      )
      .sort(SORTS[sort].compare);
  }, [bases, search, owner, sort]);
  const filtered = search.trim() !== "" || owner !== "all";
  const opened = bases.find((base) => base.kb_id === openId);

  const dialogs = (
    <>
      <CreateBaseDialog open={creating} onOpenChange={setCreating} onCreate={create} />
      {renaming !== null && (
        <RenameBaseDialog
          name={renaming.name}
          open
          onOpenChange={(open) => {
            if (!open) setRenaming(null);
          }}
          onRename={(name) => rename(renaming, name)}
        />
      )}
      {deleting !== null && (
        <ConfirmDialog
          open
          onOpenChange={(open) => {
            if (!open) setDeleting(null);
          }}
          title={`Delete ${displaySafe(deleting.name)}?`}
          confirmLabel="Delete knowledge base"
          onConfirm={() => remove(deleting)}
          onCloseAutoFocus={(event) => {
            if (!toHeading.current) return;
            event.preventDefault();
            toHeading.current = false;
            heading.current?.focus();
          }}
        >
          Its documents are deleted with it, and the assistant can no longer answer from them. This
          can&apos;t be undone.
        </ConfirmDialog>
      )}
    </>
  );

  // The dialogs stay at one place in the tree, so switching views never remounts an open one.
  if (opened !== undefined)
    return (
      <>
        <BaseDetail
          deps={deps}
          base={opened}
          onBack={() => {
            setOpenId(null);
          }}
          actions={actions}
          onDocumentCount={(count) => {
            setBases((current) =>
              current.map((b) => (b.kb_id === opened.kb_id ? { ...b, document_count: count } : b)),
            );
          }}
        />
        {dialogs}
      </>
    );

  return (
    <>
      <section
        aria-labelledby="knowledge-heading"
        className="mx-auto w-full max-w-5xl animate-in space-y-6 px-4 py-8 duration-300 fade-in-0 sm:px-6"
      >
        <header className="flex flex-wrap items-end justify-between gap-4">
          <div className="min-w-0 space-y-1">
            <h1
              id="knowledge-heading"
              ref={heading}
              tabIndex={-1}
              className="text-2xl font-semibold tracking-tight outline-none"
            >
              Knowledge
            </h1>
            <p className="max-w-prose text-sm text-muted-foreground">
              Upload documents so the assistant can answer from them. Only you can see them, unless
              you share a knowledge base with a role.
            </p>
          </div>
          <Button
            type="button"
            onClick={() => {
              setCreating(true);
            }}
          >
            <Plus />
            New knowledge base
          </Button>
        </header>

        <p role="status" className="sr-only">
          {notice}
        </p>
        {error !== null && (
          <p
            role="alert"
            className="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive"
          >
            {error}
          </p>
        )}

        {bases.length > 0 && (
          <div className="flex flex-wrap items-center gap-2">
            <label className="relative w-full sm:w-auto sm:min-w-48 sm:flex-1">
              <span className="sr-only">Search knowledge bases</span>
              <Search
                aria-hidden="true"
                className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground"
              />
              <Input
                type="search"
                value={search}
                placeholder="Search knowledge bases"
                className="pl-8"
                onChange={(event) => {
                  setSearch(event.target.value);
                }}
              />
            </label>
            {shared && (
              <select
                aria-label="Show"
                className={SELECT}
                value={owner}
                onChange={(event) => {
                  setOwner(event.target.value as Owner);
                }}
              >
                <option value="all">All</option>
                <option value="mine">Created by you</option>
                <option value="shared">Shared with you</option>
              </select>
            )}
            <select
              aria-label="Sort by"
              className={SELECT}
              value={sort}
              onChange={(event) => {
                setSort(event.target.value as BaseSort);
              }}
            >
              {(Object.keys(SORTS) as BaseSort[]).map((key) => (
                <option key={key} value={key}>
                  {SORTS[key].label}
                </option>
              ))}
            </select>
            <div
              role="group"
              aria-label="View"
              className="ml-auto flex rounded-md border p-0.5 shadow-xs sm:ml-0"
            >
              {(
                [
                  ["grid", "Grid view", <LayoutGrid key="g" />],
                  ["list", "List view", <List key="l" />],
                ] as const
              ).map(([value, label, icon]) => (
                <Button
                  key={value}
                  type="button"
                  variant="ghost"
                  size="icon-xs"
                  aria-label={label}
                  aria-pressed={layout === value}
                  className={cn(layout === value && "bg-accent text-accent-foreground")}
                  onClick={() => {
                    chooseLayout(value);
                  }}
                >
                  {icon}
                </Button>
              ))}
            </div>
          </div>
        )}

        {!loaded && (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <p className="sr-only">Loading…</p>
            {[0, 1, 2].map((n) => (
              <Skeleton key={n} className="h-36 rounded-xl" />
            ))}
          </div>
        )}

        {loaded && error === null && bases.length === 0 && (
          <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed px-6 py-14 text-center">
            <span className="flex size-11 items-center justify-center rounded-full bg-muted">
              <Library aria-hidden="true" className="size-5 text-muted-foreground" />
            </span>
            <div className="space-y-1">
              <h2 className="font-medium">No knowledge bases yet</h2>
              <p className="max-w-sm text-sm text-muted-foreground">
                Create one for a topic, such as your policies, then add files and web pages to it.
              </p>
            </div>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                setCreating(true);
              }}
            >
              <Plus />
              Create a knowledge base
            </Button>
          </div>
        )}

        {bases.length > 0 && (
          <>
            <p className="text-xs text-muted-foreground" aria-live="polite">
              {filtered
                ? `${String(shown.length)} of ${plural(bases.length, "knowledge base")}`
                : plural(bases.length, "knowledge base")}
            </p>
            {shown.length > 0 ? (
              <BaseList bases={shown} layout={layout} actions={actions} />
            ) : (
              <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed px-6 py-10 text-center text-sm">
                <p className="font-medium">No knowledge bases match</p>
                <Button
                  type="button"
                  variant="link"
                  size="sm"
                  onClick={() => {
                    setSearch("");
                    setOwner("all");
                  }}
                >
                  Clear search and filters
                </Button>
              </div>
            )}
          </>
        )}
      </section>
      {dialogs}
    </>
  );
}
