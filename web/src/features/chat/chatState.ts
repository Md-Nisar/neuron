import { displayText, type RunState } from "@/lib/stream";

export interface Failure {
  /** A fixed reason (a start-error kind or a stream error code), never server text. */
  kind: string;
  retryAfterSeconds: number | null;
}

export type MessageStatus = "done" | "streaming" | "stopped" | "failed" | "needs_approval";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  toolCalls: string[];
  status: MessageStatus;
  failure: Failure | null;
}

export interface ChatState {
  threadId: string | null;
  messages: ChatMessage[];
  running: boolean;
}

export const initialChatState: ChatState = { threadId: null, messages: [], running: false };

export type ChatAction =
  | { type: "send"; userId: string; assistantId: string; text: string }
  | { type: "progress"; assistantId: string; run: RunState }
  | { type: "start_failed"; assistantId: string; failure: Failure }
  | { type: "stopped"; assistantId: string }
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
          {
            id: action.userId,
            role: "user",
            text: action.text,
            toolCalls: [],
            status: "done",
            failure: null,
          },
          {
            id: action.assistantId,
            role: "assistant",
            text: "",
            toolCalls: [],
            status: "streaming",
            failure: null,
          },
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
          status: statusOf(run),
          failure,
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
