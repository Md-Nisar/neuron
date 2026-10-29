import { Check, ShieldAlert, X } from "lucide-react";
import { useEffect, useRef } from "react";

import { Button } from "@/components/ui/button";
import type { Decision } from "@/lib/stream";

import { viewAction } from "./approval";
import type { MessageApproval } from "./chatState";
import { APPROVAL_TEXT, failureText } from "./messages";

function outcomeText(approval: MessageApproval): string | null {
  switch (approval.state) {
    case "deciding":
      return APPROVAL_TEXT.deciding;
    case "approved":
      return APPROVAL_TEXT.approved;
    case "rejected":
      return APPROVAL_TEXT.rejected;
    case "unavailable":
      return APPROVAL_TEXT.unavailable;
    case "pending":
      return approval.failure === null ? null : failureText(approval.failure);
  }
}

/**
 * Asks the user to decide a tool call. Built only from the server's validated `approval_required`
 * payload, never from model text, and outside the Markdown renderer, which cannot produce a
 * button or this amber frame. The decision shown afterwards comes from the user's click and
 * the HTTP result, never from how the model words its next message.
 *
 * Tool name and arguments are shown in full (invisible characters made visible). If they are too
 * long to show in full, Approve is disabled: nothing is approved that was not shown.
 */
export function ApprovalCard({
  approval,
  onDecide,
}: {
  approval: MessageApproval;
  onDecide: (decision: Decision) => void;
}) {
  const { payload, state } = approval;
  const actions = payload.approval.actions.map(viewAction);
  const complete = actions.every((action) => action.complete);
  const allowed = payload.approval.allowed_decisions;
  const open = state === "pending" || state === "deciding";
  const busy = state === "deciding";
  const outcome = outcomeText(approval);
  const heading = useRef<HTMLHeadingElement>(null);

  // A card is created by a live approval request, so take the user to it: keyboard and
  // screen-reader users would otherwise not know a decision is waiting.
  useEffect(() => {
    heading.current?.focus();
  }, []);

  return (
    <section
      aria-label="Approval required"
      className="overflow-hidden rounded-xl border-2 border-warning/60 bg-warning/5 shadow-sm"
    >
      <div className="flex items-start gap-3 p-4">
        <span
          aria-hidden="true"
          className="flex size-8 shrink-0 items-center justify-center rounded-full bg-warning/15 text-warning"
        >
          <ShieldAlert className="size-4" />
        </span>
        <div className="min-w-0 flex-1">
          <h3 ref={heading} tabIndex={-1} className="font-semibold outline-offset-2">
            Approval needed
          </h3>
          <p className="mt-0.5 text-sm text-muted-foreground">
            neuron wants to run {actions.length === 1 ? "this tool" : "these tools"}. Nothing runs
            unless you approve.
          </p>
        </div>
      </div>
      <ul className="space-y-3 px-4">
        {actions.map((action, index) => (
          <li key={index} className="overflow-hidden rounded-lg border bg-card">
            <p className="border-b bg-muted/50 px-3 py-1.5 font-mono text-xs font-semibold">
              {action.name}
            </p>
            <pre className="max-h-64 overflow-auto p-3 font-mono text-xs leading-5">
              <code>{action.args}</code>
            </pre>
          </li>
        ))}
      </ul>
      {open && !complete && <p className="mt-3 px-4 text-sm">{APPROVAL_TEXT.tooLong}</p>}
      {open && (
        <div className="mt-4 flex flex-wrap gap-2 px-4">
          {allowed.includes("approve") && (
            <Button
              type="button"
              size="sm"
              disabled={busy || !complete}
              onClick={() => {
                onDecide("approve");
              }}
            >
              <Check />
              Approve
            </Button>
          )}
          {allowed.includes("reject") && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={busy}
              onClick={() => {
                onDecide("reject");
              }}
            >
              <X />
              Reject
            </Button>
          )}
        </div>
      )}
      <p
        role="status"
        aria-live="polite"
        className="px-4 pt-3 pb-4 text-sm text-muted-foreground empty:pb-1"
      >
        {outcome}
      </p>
    </section>
  );
}
