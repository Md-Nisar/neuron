import type { Failure } from "./chatState";

/** Fixed wording per reason. Server and model text is never used for these messages. */
export function failureText(failure: Failure): string {
  const { kind, retryAfterSeconds } = failure;
  switch (kind) {
    case "session_ended":
    case "unauthorized":
      return "Your session ended. Please sign in again.";
    case "forbidden":
      return "You do not have permission to do that.";
    case "not_found":
      return "That conversation could not be found. Start a new conversation.";
    case "thread_busy":
      return "The previous reply is still finishing. Try again in a moment.";
    case "approval_pending":
      return "A tool call is waiting for your approval. Decide it before sending more.";
    case "conflict":
      return "That conflicted with another request. Try again.";
    case "rate_limited":
      return retryAfterSeconds === null
        ? "Too many requests. Try again shortly."
        : `Too many requests. Try again in ${String(retryAfterSeconds)} ${retryAfterSeconds === 1 ? "second" : "seconds"}.`;
    case "invalid_request":
      return "That message was rejected. Check it and try again.";
    case "unavailable":
      return "The service is unavailable right now. Try again shortly.";
    case "server_error":
      return "Something went wrong on the server. Try again.";
    case "network":
      return "Could not reach the server. Check your connection and try again.";
    case "stream_interrupted":
      return "The connection was lost before the reply finished.";
    case "protocol_error":
    case "event_too_large":
      return "The reply could not be read.";
    case "no_result":
      return "The reply ended without an answer.";
    default:
      return "The reply failed. Try again.";
  }
}

export const APPROVAL_NOTICE =
  "This reply is waiting for your approval of a tool call. Approving is not available in this version yet.";

export function draftProblemText(
  problem: "empty" | "too_long" | "control_characters",
  max: number,
): string {
  switch (problem) {
    case "empty":
      return "Write a message first.";
    case "too_long":
      return `That message is too long. The limit is ${String(max)} characters.`;
    case "control_characters":
      return "That message contains characters that cannot be sent.";
  }
}
