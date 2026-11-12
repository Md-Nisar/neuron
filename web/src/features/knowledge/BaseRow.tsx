import { Pencil, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { displaySafe } from "@/features/chat/displaySafe";

import { ACCESS_TEXT, PROCESSING_TEXT } from "./messages";
import type { KnowledgeBase } from "./parse";

export interface BaseRowProps {
  base: KnowledgeBase;
  /** Its documents are shown below the list. */
  open: boolean;
  onOpen: () => void;
  /** Resolves true once the name is stored; false keeps the form open (the screen shows why). */
  onRename: (name: string) => Promise<boolean>;
  onDelete: () => void;
}

/**
 * One knowledge base: its name as text, where it is processed, and how it is shared with the
 * caller. Rename shows for those who administer it, the two-step delete for its owner only.
 */
export function BaseRow({ base, open, onOpen, onRename, onDelete }: BaseRowProps) {
  const [mode, setMode] = useState<"view" | "rename" | "confirm">("view");
  const [draft, setDraft] = useState("");
  const renameButton = useRef<HTMLButtonElement>(null);
  const deleteButton = useRef<HTMLButtonElement>(null);
  const back = useRef<"rename" | "delete" | null>(null);
  const name = displaySafe(base.name);
  const canRename = base.access === "owner" || base.access === "admin";

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
      <button
        type="button"
        aria-pressed={open}
        className="min-w-0 flex-1 truncate rounded text-left text-sm font-medium outline-none hover:underline focus-visible:ring-[3px] focus-visible:ring-ring/50 aria-pressed:text-primary"
        onClick={onOpen}
      >
        {name}
      </button>
      <Badge variant="secondary">{PROCESSING_TEXT[base.processing].label}</Badge>
      {base.access !== "owner" && (
        <Badge variant="outline">Shared with you · {ACCESS_TEXT[base.access].label}</Badge>
      )}
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
          {canRename && (
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
          )}
          {base.access === "owner" && (
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
          )}
        </>
      )}
    </>
  );
}
