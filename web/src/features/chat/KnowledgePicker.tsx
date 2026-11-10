import { Library } from "lucide-react";
import { useEffect, useId, useState } from "react";

import { Button } from "@/components/ui/button";
import type { DataDeps } from "@/features/data/api";
import { listBases } from "@/features/knowledge/api";
import { ApiError } from "@/lib/request";
import type { KnowledgeBase } from "@/features/knowledge/parse";

import { displaySafe } from "./displaySafe";

/** The API takes at most this many (RAG-04.04). */
export const MAX_SELECTED = 10;
/** A load refused for a while (rate limit, a restart) is tried again this often, this many times. */
export const RETRY_MS = 5000;
const RETRIES = 3;

const passing = (error: unknown) =>
  error instanceof ApiError && (error.kind === "rate_limited" || error.kind === "unavailable");

/**
 * Choose which knowledge bases a question may search; none chosen means all of them. Shown only
 * when the user has a base: knowledge off, no permission or no base shows nothing. The server
 * narrows the run to the chosen ids and never widens it, so this is a preference, not a guard.
 */
export function KnowledgePicker({
  deps,
  selected,
  onChange,
  active = true,
}: {
  deps: DataDeps;
  selected: string[];
  onChange: (ids: string[]) => void;
  /** False while the chat is hidden behind another screen; each return reloads the list. */
  active?: boolean;
}) {
  const [bases, setBases] = useState<KnowledgeBase[]>([]);
  const [open, setOpen] = useState(false);
  const [retries, setRetries] = useState(0);
  const panelId = useId();

  // Loaded on mount, each time the list is opened and each time the chat is shown again, so a
  // base made or deleted on the Knowledge screen meanwhile is seen before the next question.
  useEffect(() => {
    if (!active) return;
    let live = true;
    let retry: ReturnType<typeof setTimeout> | undefined;
    listBases(deps).then(
      (found) => {
        if (!live) return;
        setBases(found);
        // A base deleted since it was chosen is dropped from the choice.
        const known = new Set(found.map((base) => base.kb_id));
        if (selected.some((id) => !known.has(id))) onChange(selected.filter((id) => known.has(id)));
      },
      // A failed refresh keeps the list it had, so a choice in force stays visible and can be
      // changed. A passing refusal is tried again, or the picker could stay hidden all session.
      (error: unknown) => {
        if (live && passing(error) && retries < RETRIES)
          retry = setTimeout(() => {
            setRetries((n) => n + 1);
          }, RETRY_MS);
      },
    );
    return () => {
      live = false;
      clearTimeout(retry);
    };
    // `deps` is stable; `selected` is read only to prune it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, retries, active]);

  if (bases.length === 0) return null;
  const label =
    selected.length === 0
      ? "All knowledge"
      : `${String(selected.length)} of ${String(bases.length)} bases`;
  const full = selected.length >= MAX_SELECTED;
  return (
    <>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="text-muted-foreground"
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        onClick={() => {
          setOpen(!open);
        }}
      >
        <Library />
        <span className="sr-only">Knowledge to search: </span>
        {label}
      </Button>
      {open && (
        <fieldset
          id={panelId}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              setOpen(false);
            }
          }}
          className="order-last basis-full space-y-1.5 rounded-lg border px-3 py-2 text-sm"
        >
          <legend className="px-1 text-xs text-muted-foreground">
            Search only these (none chosen: all; at most {MAX_SELECTED})
          </legend>
          {bases.map((base) => {
            const checked = selected.includes(base.kb_id);
            return (
              <label key={base.kb_id} className="flex items-center gap-2">
                <input
                  type="checkbox"
                  className="size-4 accent-primary"
                  checked={checked}
                  disabled={!checked && full}
                  onChange={() => {
                    onChange(
                      checked
                        ? selected.filter((id) => id !== base.kb_id)
                        : [...selected, base.kb_id],
                    );
                  }}
                />
                <span className="truncate">{displaySafe(base.name)}</span>
              </label>
            );
          })}
        </fieldset>
      )}
    </>
  );
}
