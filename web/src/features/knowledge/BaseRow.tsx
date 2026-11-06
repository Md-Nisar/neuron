import { Pencil, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { displaySafe } from "@/features/chat/displaySafe";

import { PROCESSING_TEXT } from "./messages";
import type { KnowledgeBase } from "./parse";

export interface BaseRowProps {
  base: KnowledgeBase;
  /** Resolves true once the name is stored; false keeps the form open (the screen shows why). */
  onRename: (name: string) => Promise<boolean>;
  onDelete: () => void;
}

/** One knowledge base: its name as text, where it is processed, rename, and a two-step delete. */
export function BaseRow({ base, onRename, onDelete }: BaseRowProps) {
  const [mode, setMode] = useState<"view" | "rename" | "confirm">("view");
  const [draft, setDraft] = useState("");
  const renameButton = useRef<HTMLButtonElement>(null);
  const deleteButton = useRef<HTMLButtonElement>(null);
  const back = useRef<"rename" | "delete" | null>(null);
  const name = displaySafe(base.name);

  // Leaving the form or the confirm step removes the focused control: return to its button.
  useEffect(() => {
    if (mode !== "view" || back.current === null) return;
    (back.current === "rename" ? renameButton : deleteButton).current?.focus();
    back.current = null;
  }, [mode]);

  const leave = (from: "rename" | "delete") => {
    back.current = from;
    setMode("view");
  };

  if (mode === "rename") {
    return (
      <form
        className="flex min-w-0 flex-1 gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          void onRename(draft).then((stored) => {
            if (stored) leave("rename");
          });
        }}
      >
        <Input
          autoFocus
          aria-label={`New name for ${name}`}
          value={draft}
          onChange={(event) => {
            setDraft(event.target.value);
          }}
        />
        <Button type="submit" size="xs">
          Save
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="xs"
          onClick={() => {
            leave("rename");
          }}
        >
          Cancel
        </Button>
      </form>
    );
  }

  return (
    <>
      <p className="min-w-0 flex-1 truncate text-sm font-medium">{name}</p>
      <Badge variant="secondary">{PROCESSING_TEXT[base.processing].label}</Badge>
      {mode === "confirm" ? (
        <>
          <Button type="button" autoFocus variant="destructive" size="xs" onClick={onDelete}>
            Confirm delete
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="xs"
            onClick={() => {
              leave("delete");
            }}
          >
            Cancel
          </Button>
        </>
      ) : (
        <>
          <Button
            ref={renameButton}
            type="button"
            variant="ghost"
            size="xs"
            aria-label={`Rename ${name}`}
            onClick={() => {
              setDraft(base.name);
              setMode("rename");
            }}
          >
            <Pencil />
          </Button>
          <Button
            ref={deleteButton}
            type="button"
            variant="ghost"
            size="xs"
            aria-label={`Delete ${name}`}
            className="hover:text-destructive"
            onClick={() => {
              setMode("confirm");
            }}
          >
            <Trash2 />
          </Button>
        </>
      )}
    </>
  );
}
