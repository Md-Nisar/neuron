import { Library } from "lucide-react";
import { useEffect, useId, useState } from "react";

import { Button } from "@/components/ui/button";
import type { DataDeps } from "@/features/data/api";
import { listBases } from "@/features/knowledge/api";
import type { KnowledgeBase } from "@/features/knowledge/parse";

import { displaySafe } from "./displaySafe";

/** The API takes at most this many (RAG-04.04). */
export const MAX_SELECTED = 10;

/**
 * Choose which knowledge bases a question may search; none chosen means all of them. Shown only
 * when the user has a base: knowledge off, no permission or no base shows nothing. The server
 * narrows the run to the chosen ids and never widens it, so this is a preference, not a guard.
 */
export function KnowledgePicker({
  deps,
  selected,
  onChange,
}: {
  deps: DataDeps;
  selected: string[];
  onChange: (ids: string[]) => void;
}) {
  const [bases, setBases] = useState<KnowledgeBase[]>([]);
  const [open, setOpen] = useState(false);
  const panelId = useId();

  // Loaded on mount and each time the list is opened, so a base made meanwhile appears.
  useEffect(() => {
    let live = true;
    listBases(deps).then(
      (found) => {
        if (!live) return;
        setBases(found);
        // A base deleted since it was chosen is dropped from the choice.
        const known = new Set(found.map((base) => base.kb_id));
        if (selected.some((id) => !known.has(id))) onChange(selected.filter((id) => known.has(id)));
      },
      // A failed refresh keeps the list it had, so a choice in force stays visible and can be
      // changed; a first load that fails shows nothing.
      () => undefined,
    );
    return () => {
      live = false;
    };
    // `deps` is stable; `selected` is read only to prune it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

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
