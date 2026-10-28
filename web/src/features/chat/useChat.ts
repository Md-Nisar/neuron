import { useEffect, useReducer, useRef } from "react";

import { initialRunState, reduceRunState, streamRun, StreamStartError } from "@/lib/stream";

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
