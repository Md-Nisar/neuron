import { Check, ThumbsDown, ThumbsUp } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import type { DataDeps } from "@/features/data/api";
import { dataErrorText } from "@/features/data/messages";
import { ApiError } from "@/lib/request";

import {
  NEGATIVE_REASONS,
  REASON_LABEL,
  submitFeedback,
  type Rating,
  type Reason,
} from "./feedback";

type Phase =
  { name: "idle" } | { name: "choosing" } | { name: "sending" } | { name: "done"; rating: Rating };

function errorText(error: unknown): string {
  if (error instanceof ApiError && error.kind === "forbidden") {
    return "You do not have permission to rate answers.";
  }
  if (error instanceof ApiError && error.kind === "not_found") {
    return "That conversation no longer exists.";
  }
  return dataErrorText(error);
}

function ratingText(rating: Rating): string {
  const label = rating.score === 1 ? "Helpful" : "Not helpful";
  return rating.reason === null ? label : `${label} (${REASON_LABEL[rating.reason]})`;
}

const PILL = "h-7 rounded-full px-3 text-xs font-normal";

/**
 * Thumbs up or down for one answer, with a fixed reason for a thumbs down. One rating per run:
 * the server keeps the first, and what is shown afterwards is what it answered. A failure is
 * shown beside the buttons and never blocks the chat.
 */
export function FeedbackBar({
  deps,
  threadId,
  runId,
}: {
  deps: DataDeps;
  threadId: string;
  runId: string;
}) {
  const [phase, setPhase] = useState<Phase>({ name: "idle" });
  const [error, setError] = useState<string | null>(null);
  const sending = useRef(false);
  const choosing = useRef<HTMLFieldSetElement>(null);
  const result = useRef<HTMLParagraphElement>(null);

  // The buttons that had focus disappear when the next step appears: follow them.
  useEffect(() => {
    if (phase.name === "choosing") choosing.current?.focus();
    if (phase.name === "done") result.current?.focus();
  }, [phase.name]);

  async function send(rating: Rating): Promise<void> {
    if (sending.current) return; // a double click while the first request is in flight
    sending.current = true;
    setError(null);
    setPhase({ name: "sending" });
    try {
      setPhase({ name: "done", rating: await submitFeedback(deps, threadId, runId, rating) });
    } catch (failure) {
      setError(errorText(failure));
      setPhase(rating.score === 1 ? { name: "idle" } : { name: "choosing" });
    } finally {
      sending.current = false;
    }
  }

  if (phase.name === "done") {
    return (
      <p
        ref={result}
        tabIndex={-1}
        className="flex items-center gap-1.5 px-1.5 text-xs text-muted-foreground outline-none"
      >
        <Check aria-hidden="true" className="size-3.5" />
        Thanks for your feedback. Your rating: {ratingText(phase.rating)}.
      </p>
    );
  }

  const busy = phase.name === "sending";
  return (
    <div className="text-xs">
      {phase.name !== "choosing" && (
        <div role="group" aria-label="Rate this answer" className="flex items-center gap-0.5">
          <span className="sr-only">Was this answer helpful?</span>
          <Button
            type="button"
            variant="ghost"
            size="icon-xs"
            aria-label="Helpful"
            title="Helpful"
            disabled={busy}
            onClick={() => void send({ score: 1, reason: null })}
          >
            <ThumbsUp />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon-xs"
            aria-label="Not helpful"
            title="Not helpful"
            disabled={busy}
            onClick={() => {
              setError(null);
              setPhase({ name: "choosing" });
            }}
          >
            <ThumbsDown />
          </Button>
          {busy && <span className="px-1.5 text-muted-foreground">Sending…</span>}
        </div>
      )}
      {phase.name === "choosing" && (
        <fieldset
          ref={choosing}
          tabIndex={-1}
          className="mt-1 flex animate-in flex-wrap items-center gap-1.5 rounded-xl border bg-card p-2.5 duration-200 fade-in-0 outline-none"
        >
          <legend className="float-left mr-1 w-full pb-1.5 pl-0.5 text-xs font-medium text-foreground">
            What was wrong?
          </legend>
          {NEGATIVE_REASONS.map((reason: Reason) => (
            <Button
              key={reason}
              type="button"
              variant="outline"
              className={PILL}
              onClick={() => void send({ score: -1, reason })}
            >
              {REASON_LABEL[reason]}
            </Button>
          ))}
          <Button
            type="button"
            variant="ghost"
            className={PILL}
            onClick={() => void send({ score: -1, reason: null })}
          >
            No reason
          </Button>
        </fieldset>
      )}
      {error !== null && (
        <p role="alert" className="mt-1 px-1.5 text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
