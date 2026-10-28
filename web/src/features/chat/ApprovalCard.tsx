import { useEffect, useRef } from "react";

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
 * button or this double border. The decision shown afterwards comes from the user's click and
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
    <section aria-label="Approval required" className="mt-2 rounded border-4 border-double p-3">
      <h3 ref={heading} tabIndex={-1} className="font-semibold outline-offset-2">
        Approval needed
      </h3>
      <p className="text-sm">
        neuron wants to run {actions.length === 1 ? "this tool" : "these tools"}. Nothing runs
        unless you approve.
      </p>
      <ul className="mt-2 space-y-2">
        {actions.map((action, index) => (
          <li key={index}>
            <p className="font-mono font-semibold">{action.name}</p>
            <pre className="max-h-64 overflow-auto rounded border p-2 text-sm">
              <code>{action.args}</code>
            </pre>
          </li>
        ))}
      </ul>
      {open && !complete && <p className="mt-2">{APPROVAL_TEXT.tooLong}</p>}
      {open && (
        <div className="mt-2 flex flex-wrap gap-2">
          {allowed.includes("approve") && (
            <button
              type="button"
              className="rounded border px-3 py-1"
              disabled={busy || !complete}
              onClick={() => {
                onDecide("approve");
              }}
            >
              Approve
            </button>
          )}
          {allowed.includes("reject") && (
            <button
              type="button"
              className="rounded border px-3 py-1"
              disabled={busy}
              onClick={() => {
                onDecide("reject");
              }}
            >
              Reject
            </button>
          )}
        </div>
      )}
      <p role="status" aria-live="polite" className="mt-2">
        {outcome}
      </p>
    </section>
  );
}
