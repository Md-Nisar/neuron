import { useEffect, useReducer, useRef } from "react";

import {
  initialRunState,
  reduceRunState,
  streamRun,
  StreamStartError,
  type Decision,
} from "@/lib/stream";

import { approvalStreamPath } from "./approval";

import { chatReducer, initialChatState, retryableText, type Failure } from "./chatState";
import { checkDraft, type DraftProblem } from "./limits";

export interface ChatDeps {
  apiUrl: string;
  getAccessToken: () => string | null;
  /** The token is missing or the API refused it (401): the user must sign in again. */
  onSessionEnded: () => void;
  maxChars: number;
  fetch?: typeof fetch;
}

export function useChat(deps: ChatDeps) {
  const [state, dispatch] = useReducer(chatReducer, initialChatState);
  const abort = useRef<AbortController | null>(null);
  const deciding = useRef(new Set<string>());

  useEffect(
    () => () => {
      abort.current?.abort();
    },
    [],
  );

  async function run(text: string): Promise<void> {
    const userId = crypto.randomUUID();
    const assistantId = crypto.randomUUID();
    dispatch({ type: "send", userId, assistantId, text });

    const token = deps.getAccessToken();
    if (token === null) {
      dispatch({
        type: "start_failed",
        assistantId,
        failure: { kind: "session_ended", retryAfterSeconds: null },
      });
      dispatch({ type: "finished" });
      deps.onSessionEnded();
      return;
    }
    const controller = new AbortController();
    abort.current = controller;
    let current = initialRunState;
    try {
      const events = streamRun({
        baseUrl: deps.apiUrl,
        path: "/v1/agent/stream",
        token,
        body: { message: text, ...(state.threadId === null ? {} : { thread_id: state.threadId }) },
        signal: controller.signal,
        ...(deps.fetch === undefined ? {} : { fetch: deps.fetch }),
      });
      for await (const event of events) {
        current = reduceRunState(current, event);
        dispatch({ type: "progress", assistantId, run: current });
      }
      if (controller.signal.aborted) dispatch({ type: "stopped", assistantId });
    } catch (error) {
      const failure: Failure =
        error instanceof StreamStartError
          ? { kind: error.kind, retryAfterSeconds: error.retryAfterSeconds }
          : { kind: "unexpected", retryAfterSeconds: null };
      dispatch({ type: "start_failed", assistantId, failure });
      if (failure.kind === "unauthorized") deps.onSessionEnded();
    } finally {
      abort.current = null;
      dispatch({ type: "finished" });
    }
  }

  /**
   * Decide a pending approval and stream the continuation. Acts only on the approval the server
   * sent for that message; one decision per approval, however many clicks.
   */
  async function decide(messageId: string, decision: Decision): Promise<void> {
    const approval = state.messages.find((message) => message.id === messageId)?.approval;
    if (approval?.state !== "pending" || state.running) return;
    const { approval_id: approvalId, allowed_decisions: allowed } = approval.payload.approval;
    // The ref is checked synchronously, so a double-click cannot start two decisions.
    if (!allowed.includes(decision) || deciding.current.has(approvalId)) return;
    deciding.current.add(approvalId);
    dispatch({ type: "approval_deciding", messageId });

    const fail = (failure: Failure): void => {
      dispatch({ type: "approval_failed", messageId, failure });
      dispatch({ type: "finished" });
    };
    try {
      const token = deps.getAccessToken();
      if (token === null) {
        fail({ kind: "session_ended", retryAfterSeconds: null });
        deps.onSessionEnded();
        return;
      }
      const controller = new AbortController();
      abort.current = controller;
      const assistantId = crypto.randomUUID();
      let started = false;
      let current = initialRunState;
      try {
        const events = streamRun({
          baseUrl: deps.apiUrl,
          path: approvalStreamPath(approval.payload),
          token,
          body: { decision },
          signal: controller.signal,
          ...(deps.fetch === undefined ? {} : { fetch: deps.fetch }),
        });
        for await (const event of events) {
          if (!started) {
            // The server accepted the decision: it is single-use from here on.
            started = true;
            dispatch({ type: "continue", assistantId });
            dispatch({ type: "approval_decided", messageId, decision });
          }
          current = reduceRunState(current, event);
          dispatch({ type: "progress", assistantId, run: current });
        }
        if (!started) fail({ kind: "cancelled", retryAfterSeconds: null });
        else if (controller.signal.aborted) dispatch({ type: "stopped", assistantId });
      } catch (error) {
        if (error instanceof StreamStartError && error.kind === "not_found") {
          // Decided elsewhere or expired. Which decision, if any, was made is not known here.
          dispatch({ type: "approval_unavailable", messageId });
          dispatch({ type: "finished" });
        } else {
          const kind = error instanceof StreamStartError ? error.kind : "unexpected";
          const retryAfterSeconds =
            error instanceof StreamStartError ? error.retryAfterSeconds : null;
          fail({ kind, retryAfterSeconds });
          if (kind === "unauthorized") deps.onSessionEnded();
        }
      }
    } finally {
      abort.current = null;
      deciding.current.delete(approvalId);
      dispatch({ type: "finished" });
    }
  }

  /** Validate and send. Returns what is wrong with the draft, or null if it was sent. */
  async function send(raw: string): Promise<DraftProblem | null> {
    if (state.running) return null;
    const { text, problem } = checkDraft(raw, deps.maxChars);
    if (problem !== null) return problem;
    await run(text);
    return null;
  }

  const retryText = retryableText(state);

  return {
    messages: state.messages,
    threadId: state.threadId,
    running: state.running,
    canRetry: retryText !== null,
    send,
    decide,
    stop: () => {
      abort.current?.abort();
    },
    retry: async () => {
      if (retryText === null) return;
      dispatch({ type: "drop_last_turn" });
      await run(retryText);
    },
    newConversation: () => {
      abort.current?.abort();
      dispatch({ type: "reset" });
    },
  };
}
