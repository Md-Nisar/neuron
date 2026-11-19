import { ArrowLeft, Library } from "lucide-react";
import { Tabs } from "radix-ui";
import { useEffect, useRef } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { displaySafe } from "@/features/chat/displaySafe";
import type { DataDeps } from "@/features/data/api";

import { BaseMenu, type BaseActions } from "./BaseList";
import { DocumentsPanel } from "./DocumentsPanel";
import { formatDate, formatDateTime } from "./format";
import { GrantsPanel } from "./GrantsPanel";
import { ACCESS_TEXT, languageLabel, PROCESSING_TEXT } from "./messages";
import type { KnowledgeBase } from "./parse";

const TAB =
  "-mb-px border-b-2 border-transparent px-1 pb-2.5 text-sm font-medium text-muted-foreground outline-none transition-colors hover:text-foreground focus-visible:rounded-sm focus-visible:ring-[3px] focus-visible:ring-ring/50 data-[state=active]:border-foreground data-[state=active]:text-foreground";

/** One knowledge base's page: what it is, its documents and, for its admins, who it is shared with. */
export function BaseDetail({
  deps,
  base,
  onBack,
  actions,
  onDocumentCount,
}: {
  deps: DataDeps;
  base: KnowledgeBase;
  onBack: () => void;
  actions: BaseActions;
  onDocumentCount: (count: number) => void;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  const name = displaySafe(base.name);
  const admin = base.access === "owner" || base.access === "admin";

  // Opening a base moves focus to its name, so a screen reader announces the new page.
  useEffect(() => {
    heading.current?.focus();
  }, [base.kb_id]);

  return (
    <section
      aria-labelledby="base-heading"
      className="mx-auto w-full max-w-5xl animate-in space-y-6 px-4 py-6 duration-200 fade-in-0 sm:px-6"
    >
      <nav aria-label="Breadcrumb">
        <Button type="button" variant="ghost" size="sm" className="-ml-2.5" onClick={onBack}>
          <ArrowLeft />
          All knowledge bases
        </Button>
      </nav>
      <header className="flex items-start gap-3">
        <span className="hidden size-11 shrink-0 items-center justify-center rounded-xl bg-muted sm:flex">
          <Library aria-hidden="true" className="size-5 text-muted-foreground" />
        </span>
        <div className="min-w-0 flex-1 space-y-2">
          <h1
            id="base-heading"
            ref={heading}
            tabIndex={-1}
            className="truncate text-2xl font-semibold tracking-tight outline-none"
          >
            {name}
          </h1>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs text-muted-foreground">
            <Badge variant="secondary">{PROCESSING_TEXT[base.processing].label}</Badge>
            {base.access !== "owner" && (
              <Badge variant="outline">Shared with you · {ACCESS_TEXT[base.access].label}</Badge>
            )}
            <span>{languageLabel(base.language)}</span>
            <span>
              Created{" "}
              <time dateTime={base.created_at} title={formatDateTime(base.created_at)}>
                {formatDate(base.created_at)}
              </time>
            </span>
          </div>
        </div>
        <BaseMenu base={base} actions={{ ...actions, onOpen: () => heading.current?.focus() }} />
      </header>

      <Tabs.Root defaultValue="documents" className="space-y-5">
        <Tabs.List aria-label={`${name} sections`} className="flex gap-5 border-b">
          <Tabs.Trigger value="documents" className={TAB}>
            Documents
          </Tabs.Trigger>
          {admin && (
            <Tabs.Trigger value="sharing" className={TAB}>
              Sharing
            </Tabs.Trigger>
          )}
        </Tabs.List>
        <Tabs.Content value="documents" className="outline-none">
          <DocumentsPanel deps={deps} base={base} onTotal={onDocumentCount} />
        </Tabs.Content>
        {admin && (
          <Tabs.Content value="sharing" className="outline-none">
            <GrantsPanel deps={deps} base={base} />
          </Tabs.Content>
        )}
      </Tabs.Root>
    </section>
  );
}
