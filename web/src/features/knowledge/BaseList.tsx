import { FolderOpen, Library, MoreHorizontal, Pencil, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { displaySafe } from "@/features/chat/displaySafe";
import { cn } from "@/lib/utils";

import { formatDate, formatDateTime, plural } from "./format";
import { ACCESS_TEXT, PROCESSING_TEXT } from "./messages";
import type { KnowledgeBase } from "./parse";

export type Layout = "grid" | "list";

export interface BaseActions {
  onOpen: (base: KnowledgeBase) => void;
  onRename: (base: KnowledgeBase) => void;
  onDelete: (base: KnowledgeBase) => void;
}

/** Open, and what the caller's access allows: rename for its admins, delete for its owner. */
export function BaseMenu({ base, actions }: { base: KnowledgeBase; actions: BaseActions }) {
  const name = displaySafe(base.name);
  const canRename = base.access === "owner" || base.access === "admin";
  return (
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label={`Actions for ${name}`}
          className="relative z-10 text-muted-foreground"
        >
          <MoreHorizontal />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem
          onSelect={() => {
            actions.onOpen(base);
          }}
        >
          <FolderOpen />
          Open
        </DropdownMenuItem>
        {canRename && (
          <DropdownMenuItem
            onSelect={() => {
              actions.onRename(base);
            }}
          >
            <Pencil />
            Rename
          </DropdownMenuItem>
        )}
        {base.access === "owner" && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              destructive
              onSelect={() => {
                actions.onDelete(base);
              }}
            >
              <Trash2 />
              Delete
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function Badges({ base }: { base: KnowledgeBase }) {
  return (
    <>
      <Badge variant="secondary">{PROCESSING_TEXT[base.processing].label}</Badge>
      {base.access !== "owner" && (
        <Badge variant="outline">Shared with you · {ACCESS_TEXT[base.access].label}</Badge>
      )}
    </>
  );
}

function Meta({ base }: { base: KnowledgeBase }) {
  return (
    <>
      {base.document_count !== null && (
        <>
          <span>{plural(base.document_count, "document")}</span>
          <span aria-hidden="true">·</span>
        </>
      )}
      <span>
        Created{" "}
        <time dateTime={base.created_at} title={formatDateTime(base.created_at)}>
          {formatDate(base.created_at)}
        </time>
      </span>
    </>
  );
}

/**
 * The bases as cards or rows. The name is the one button that opens a base; its `::after`
 * stretches over the card, so the whole card is a click target but one stop for the keyboard.
 */
export function BaseList({
  bases,
  layout,
  actions,
}: {
  bases: KnowledgeBase[];
  layout: Layout;
  actions: BaseActions;
}) {
  const open = (base: KnowledgeBase) => (
    <button
      type="button"
      className="min-w-0 truncate rounded-sm text-left font-medium outline-none after:absolute after:inset-0 after:rounded-[inherit] focus-visible:after:ring-[3px] focus-visible:after:ring-ring/50"
      onClick={() => {
        actions.onOpen(base);
      }}
    >
      {displaySafe(base.name)}
    </button>
  );

  if (layout === "list")
    return (
      <ul aria-label="Your knowledge bases" className="divide-y rounded-xl border">
        {bases.map((base) => (
          <li
            key={base.kb_id}
            className="relative flex items-center gap-3 rounded-[inherit] px-4 py-3 transition-colors first:rounded-t-xl last:rounded-b-xl hover:bg-accent/50"
          >
            <Library aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
            <div className="flex min-w-0 flex-1 flex-col gap-0.5 text-sm sm:flex-row sm:items-center sm:gap-3">
              {open(base)}
              <span className="flex shrink-0 gap-1.5 text-xs text-muted-foreground sm:ml-auto">
                <Meta base={base} />
              </span>
            </div>
            <span className="hidden shrink-0 gap-1.5 md:flex">
              <Badges base={base} />
            </span>
            <BaseMenu base={base} actions={actions} />
          </li>
        ))}
      </ul>
    );

  return (
    <ul aria-label="Your knowledge bases" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {bases.map((base) => (
        <li
          key={base.kb_id}
          className={cn(
            "group relative flex min-h-36 flex-col gap-3 rounded-xl border bg-card p-4 shadow-xs transition-[border-color,box-shadow]",
            "hover:border-foreground/20 hover:shadow-sm",
          )}
        >
          <div className="flex items-start justify-between gap-2">
            <span className="flex size-9 items-center justify-center rounded-lg bg-muted">
              <Library aria-hidden="true" className="size-4 text-muted-foreground" />
            </span>
            <BaseMenu base={base} actions={actions} />
          </div>
          <div className="flex min-w-0 flex-col gap-1 text-sm">
            {open(base)}
            <span className="flex flex-wrap gap-1.5 text-xs text-muted-foreground">
              <Meta base={base} />
            </span>
          </div>
          <div className="mt-auto flex flex-wrap gap-1.5">
            <Badges base={base} />
          </div>
        </li>
      ))}
    </ul>
  );
}
