import { call, type DataDeps } from "@/features/data/api";
import { record } from "@/features/data/parse";
import { SAFE_ID } from "@/lib/stream";

/** The fixed reasons the API accepts, by score. There is no free text. */
export const POSITIVE_REASONS = ["helpful", "accurate"] as const;
export const NEGATIVE_REASONS = ["inaccurate", "unhelpful", "unsafe", "other"] as const;
export type Reason = (typeof POSITIVE_REASONS)[number] | (typeof NEGATIVE_REASONS)[number];
export type Score = 1 | -1;

export const REASON_LABEL: Record<Reason, string> = {
  helpful: "Helpful",
  accurate: "Accurate",
  inaccurate: "Inaccurate",
  unhelpful: "Not useful",
  unsafe: "Unsafe",
  other: "Other",
};

export interface Rating {
  score: Score;
  reason: Reason | null;
}

const ALL_REASONS: readonly string[] = [...POSITIVE_REASONS, ...NEGATIVE_REASONS];

export function parseRating(body: unknown): Rating {
  const item = record(body);
  const score = item["score"];
  if (score !== 1 && score !== -1) throw new TypeError("shape");
  const reason = item["reason"];
  if (reason !== null && (typeof reason !== "string" || !ALL_REASONS.includes(reason))) {
    throw new TypeError("shape");
  }
  return { score, reason: reason as Reason | null };
}

/** Rate one answer. The first rating of a run stands: the response is the one that is stored. */
export function submitFeedback(
  deps: DataDeps,
  threadId: string,
  runId: string,
  rating: Rating,
): Promise<Rating> {
  // Both ids join a URL path: they are checked again here.
  if (!SAFE_ID.test(threadId) || !SAFE_ID.test(runId)) {
    return Promise.reject(new TypeError("unsafe identifiers"));
  }
  return call(deps, {
    path: `/v1/threads/${encodeURIComponent(threadId)}/runs/${encodeURIComponent(runId)}/feedback`,
    method: "POST",
    body: { score: rating.score, ...(rating.reason === null ? {} : { reason: rating.reason }) },
    parse: parseRating,
  });
}
