import { useEffect, useRef, useState } from "react";

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
      <p ref={result} tabIndex={-1} className="mt-1 text-xs opacity-70">
        Thanks for your feedback. Your rating: {ratingText(phase.rating)}.
      </p>
    );
  }

  const busy = phase.name === "sending";
  return (
    <div className="mt-1 text-xs">
      {phase.name !== "choosing" && (
        <div role="group" aria-label="Rate this answer" className="flex flex-wrap gap-2">
          <span className="opacity-70">Was this answer helpful?</span>
          <button
            type="button"
            className="rounded border px-2 py-0.5"
            disabled={busy}
            onClick={() => void send({ score: 1, reason: null })}
          >
            Helpful
          </button>
          <button
            type="button"
            className="rounded border px-2 py-0.5"
            disabled={busy}
            onClick={() => {
              setError(null);
              setPhase({ name: "choosing" });
            }}
          >
            Not helpful
          </button>
        </div>
      )}
      {phase.name === "choosing" && (
        <fieldset ref={choosing} tabIndex={-1} className="flex flex-wrap gap-2">
          <legend className="opacity-70">What was wrong?</legend>
          {NEGATIVE_REASONS.map((reason: Reason) => (
            <button
              key={reason}
              type="button"
              className="rounded border px-2 py-0.5"
              onClick={() => void send({ score: -1, reason })}
            >
              {REASON_LABEL[reason]}
            </button>
          ))}
          <button
            type="button"
            className="rounded border px-2 py-0.5"
            onClick={() => void send({ score: -1, reason: null })}
          >
            No reason
          </button>
        </fieldset>
      )}
      {busy && <p className="opacity-70">Sending…</p>}
      {error !== null && (
        <p role="alert" className="mt-1">
          {error}
        </p>
      )}
    </div>
  );
}
