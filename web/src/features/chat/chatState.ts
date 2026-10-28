import { displayText, type ApprovalRequired, type Decision, type RunState } from "@/lib/stream";

export interface Failure {
  /** A fixed reason (a start-error kind or a stream error code), never server text. */
  kind: string;
  retryAfterSeconds: number | null;
}

/** What the user has done with a pending approval; set by clicks and HTTP results, never by text. */
export type ApprovalState = "pending" | "deciding" | "approved" | "rejected" | "unavailable";

export interface MessageApproval {
  payload: ApprovalRequired;
  state: ApprovalState;
  /** Why the last attempt did not go through (the approval stays decidable), if it did not. */
  failure: Failure | null;
}

/** A tool call from an earlier session that did not complete, as the server recorded it. */
export interface SkippedTool {
  name: string;
  why: "pending" | "rejected" | "failed";
}

export type MessageStatus = "done" | "streaming" | "stopped" | "failed" | "needs_approval";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  toolCalls: string[];
  skipped: SkippedTool[];
  /** The server's id for the run that wrote this reply (what a rating is filed under). */
  runId: string | null;
  status: MessageStatus;
  failure: Failure | null;
  /** Set only from a validated `approval_required` event. */
  approval: MessageApproval | null;
}

export interface ChatState {
  threadId: string | null;
  messages: ChatMessage[];
  running: boolean;
  /** An opened conversation was longer than one page: its earliest messages are not shown. */
  earlierHidden: boolean;
}

export const initialChatState: ChatState = {
  threadId: null,
  messages: [],
  running: false,
  earlierHidden: false,
};

export type ChatAction =
  | { type: "send"; userId: string; assistantId: string; text: string }
  | { type: "progress"; assistantId: string; run: RunState }
  | { type: "start_failed"; assistantId: string; failure: Failure }
  | { type: "stopped"; assistantId: string }
  | { type: "continue"; assistantId: string }
  | { type: "approval_deciding"; messageId: string }
  | { type: "approval_decided"; messageId: string; decision: Decision }
  | { type: "approval_unavailable"; messageId: string }
  | { type: "approval_failed"; messageId: string; failure: Failure }
  | { type: "open"; threadId: string; messages: ChatMessage[]; earlierHidden: boolean }
  | { type: "attach_approval"; messageId: string; payload: ApprovalRequired }
  | { type: "finished" }
  | { type: "drop_last_turn" }
  | { type: "reset" };

function update(
  messages: ChatMessage[],
  id: string,
  change: (message: ChatMessage) => ChatMessage,
): ChatMessage[] {
  return messages.map((message) => (message.id === id ? change(message) : message));
}

function newMessage(
  id: string,
  role: ChatMessage["role"],
  text: string,
  status: MessageStatus,
): ChatMessage {
  return {
    id,
    role,
    text,
    toolCalls: [],
    skipped: [],
    runId: null,
    status,
    failure: null,
    approval: null,
  };
}

function setApproval(
  messages: ChatMessage[],
  id: string,
  change: Partial<Pick<MessageApproval, "state" | "failure">>,
): ChatMessage[] {
  return update(messages, id, (message) =>
    message.approval === null
      ? message
      : { ...message, approval: { ...message.approval, ...change } },
  );
}

function statusOf(run: RunState): MessageStatus {
  switch (run.status) {
    case "completed":
      return "done";
    case "approval_required":
      return "needs_approval";
    case "failed":
      return "failed";
    default:
      return "streaming";
  }
}

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case "send":
      return {
        ...state,
        running: true,
        messages: [
          ...state.messages,
          newMessage(action.userId, "user", action.text, "done"),
          newMessage(action.assistantId, "assistant", "", "streaming"),
        ],
      };
    case "progress": {
      const { run } = action;
      const failure = run.error === null ? null : { kind: run.error.code, retryAfterSeconds: null };
      return {
        ...state,
        threadId: run.ids?.threadId ?? state.threadId,
        messages: update(state.messages, action.assistantId, (message) => ({
          ...message,
          text: displayText(run),
          toolCalls: run.toolCalls,
          runId: run.ids?.runId ?? message.runId,
          status: statusOf(run),
          failure,
          approval:
            message.approval ??
            (run.approval === null
              ? null
              : { payload: run.approval, state: "pending", failure: null }),
        })),
      };
    }
    case "start_failed":
      return {
        ...state,
        messages: update(state.messages, action.assistantId, (message) => ({
          ...message,
          status: "failed",
          failure: action.failure,
        })),
      };
    case "stopped":
      return {
        ...state,
        messages: update(state.messages, action.assistantId, (message) =>
          message.status === "streaming" ? { ...message, status: "stopped" } : message,
        ),
      };
    case "continue":
      // The decision was accepted: the continuation is a new reply under the same turn.
      return {
        ...state,
        running: true,
        messages: [...state.messages, newMessage(action.assistantId, "assistant", "", "streaming")],
      };
    case "approval_deciding":
      return {
        ...state,
        running: true,
        messages: setApproval(state.messages, action.messageId, {
          state: "deciding",
          failure: null,
        }),
      };
    case "approval_decided":
      return {
        ...state,
        messages: setApproval(state.messages, action.messageId, {
          state: action.decision === "approve" ? "approved" : "rejected",
          failure: null,
        }),
      };
    case "approval_unavailable":
      return {
        ...state,
        messages: setApproval(state.messages, action.messageId, {
          state: "unavailable",
          failure: null,
        }),
      };
    case "approval_failed":
      return {
        ...state,
        messages: setApproval(state.messages, action.messageId, {
          state: "pending",
          failure: action.failure,
        }),
      };
    case "open":
      return {
        threadId: action.threadId,
        messages: action.messages,
        running: false,
        earlierHidden: action.earlierHidden,
      };
    case "attach_approval":
      // Only a message still waiting on a decision takes a card, and only once.
      return {
        ...state,
        messages: update(state.messages, action.messageId, (message) =>
          message.approval === null && message.skipped.some((tool) => tool.why === "pending")
            ? { ...message, approval: { payload: action.payload, state: "pending", failure: null } }
            : message,
        ),
      };
    case "finished":
      // A stream always ends in a terminal state; anything still "streaming" lost its result.
      return {
        ...state,
        running: false,
        messages: state.messages.map((message) =>
          message.status === "streaming"
            ? {
                ...message,
                status: "failed",
                failure: { kind: "no_result", retryAfterSeconds: null },
              }
            : message,
        ),
      };
    case "drop_last_turn":
      return { ...state, messages: state.messages.slice(0, -2) };
    case "reset":
      return initialChatState;
  }
}

/** The last user message, if the run after it failed or was stopped: what Retry would resend. */
export function retryableText(state: ChatState): string | null {
  if (state.running) return null;
  const last = state.messages.at(-1);
  const previous = state.messages.at(-2);
  if (last?.role !== "assistant" || previous?.role !== "user") return null;
  return last.status === "failed" || last.status === "stopped" ? previous.text : null;
}
