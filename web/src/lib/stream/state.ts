import type { ApprovalRequired, FinalResponse, StreamEvent } from "./events";

export type RunStatus = "idle" | "streaming" | "completed" | "approval_required" | "failed";

/** What the UI shows for one run, built only from the events. */
export interface RunState {
  status: RunStatus;
  /** Live preview of the answer; `final` replaces it. Best effort, never authoritative. */
  preview: string;
  /** Tool names as announced while streaming (never arguments). */
  toolCalls: string[];
  ids: { requestId: string; threadId: string; runId?: string } | null;
  /** The validated answer, set only by `final`. */
  final: FinalResponse | null;
  /** Set only by `approval_required`; the one source for the approval card. */
  approval: ApprovalRequired | null;
  error: { code: string; retryable: boolean } | null;
}

export const initialRunState: RunState = {
  status: "idle",
  preview: "",
  toolCalls: [],
  ids: null,
  final: null,
  approval: null,
  error: null,
};

/** The text to show: the validated answer once there is one, else the preview so far. */
export function displayText(state: RunState): string {
  return state.final?.answer ?? state.preview;
}

/**
 * Fold one event into the run state. `token` deltas only build a preview; `final` replaces it.
 * A partial preview is kept after `error` or `approval_required` so the user sees what arrived.
 */
export function reduceRunState(state: RunState, event: StreamEvent): RunState {
  switch (event.type) {
    case "run_started": {
      const { request_id, thread_id, run_id } = event.data;
      return {
        ...initialRunState,
        status: "streaming",
        ids: {
          requestId: request_id,
          threadId: thread_id,
          ...(run_id === undefined ? {} : { runId: run_id }),
        },
      };
    }
    case "token":
      return state.final === null ? { ...state, preview: state.preview + event.data.text } : state;
    case "tool_call":
      return { ...state, toolCalls: [...state.toolCalls, event.data.name] };
    case "final":
      return { ...state, status: "completed", final: event.data, preview: "", error: null };
    case "approval_required":
      return { ...state, status: "approval_required", approval: event.data };
    case "error":
      return { ...state, status: "failed", error: event.data };
    case "done":
      // A stream that ends while still "streaming" produced no result at all.
      return state.status === "streaming"
        ? { ...state, status: "failed", error: { code: "no_result", retryable: true } }
        : state;
    default:
      return state;
  }
}
