import { describe, expect, it } from "vitest";

import { initialRunState, reduceRunState, type RunState, type StreamEvent } from "@/lib/stream";

import {
  chatReducer,
  initialChatState,
  retryableText,
  type ChatState,
  type MessageStatus,
} from "./chatState";

const started: StreamEvent = { type: "run_started", data: { request_id: "r", thread_id: "t1" } };
const fold = (events: StreamEvent[]): RunState => events.reduce(reduceRunState, initialRunState);
const sent = (text = "hi"): ChatState =>
  chatReducer(initialChatState, { type: "send", userId: "u", assistantId: "a", text });

/** The chat after the run ended, with the assistant's message in `status`. */
const settled = (state: ChatState, status: MessageStatus): ChatState => ({
  ...state,
  running: false,
  messages: state.messages.map((m) => (m.role === "assistant" ? { ...m, status } : m)),
});

describe("chatReducer", () => {
  it("send adds the user message and a streaming placeholder and marks the chat running", () => {
    const state = sent("hello");

    expect(state.running).toBe(true);
    expect(state.messages.map((m) => [m.role, m.text, m.status])).toEqual([
      ["user", "hello", "done"],
      ["assistant", "", "streaming"],
    ]);
  });

  it("progress shows the preview, then final replaces it, and remembers the thread", () => {
    let state = sent();
    state = chatReducer(state, {
      type: "progress",
      assistantId: "a",
      run: fold([started, { type: "token", data: { text: "dra" } }]),
    });
    expect(state.messages[1]).toMatchObject({ text: "dra", status: "streaming" });

    const final: StreamEvent = {
      type: "final",
      data: {
        request_id: "r",
        thread_id: "t1",
        answer: "done!",
        used_tools: [],
        confidence: 1,
        refused: false,
        clarification_needed: false,
      },
    };
    state = chatReducer(state, {
      type: "progress",
      assistantId: "a",
      run: fold([started, { type: "token", data: { text: "dra" } }, final]),
    });

    expect(state.messages[1]).toMatchObject({ text: "done!", status: "done" });
    expect(state.threadId).toBe("t1");
  });

  it("keeps the partial answer when the run fails", () => {
    const run = fold([
      started,
      { type: "token", data: { text: "par" } },
      { type: "error", data: { code: "stream_interrupted", retryable: true } },
    ]);
    const state = chatReducer(sent(), { type: "progress", assistantId: "a", run });

    expect(state.messages[1]).toMatchObject({
      text: "par",
      status: "failed",
      failure: { kind: "stream_interrupted" },
    });
  });

  it("stopped only changes a message that is still streaming", () => {
    const done = chatReducer(sent(), {
      type: "progress",
      assistantId: "a",
      run: { ...initialRunState, status: "completed" },
    });

    expect(chatReducer(done, { type: "stopped", assistantId: "a" }).messages[1]?.status).toBe(
      "done",
    );
    expect(chatReducer(sent(), { type: "stopped", assistantId: "a" }).messages[1]?.status).toBe(
      "stopped",
    );
  });

  it("finished turns a message that never reached a result into a failure", () => {
    const state = chatReducer(sent(), { type: "finished" });

    expect(state.running).toBe(false);
    expect(state.messages[1]).toMatchObject({ status: "failed", failure: { kind: "no_result" } });
  });

  it("reset forgets the thread and the messages", () => {
    expect(chatReducer(sent(), { type: "reset" })).toEqual(initialChatState);
  });
});

describe("attach_approval", () => {
  const payload = {
    request_id: "r",
    thread_id: "t1",
    approval: {
      approval_id: "a1",
      actions: [{ name: "x", args: {} }],
      allowed_decisions: ["approve" as const],
    },
  };
  const opened = (why: "pending" | "rejected"): ChatState =>
    chatReducer(initialChatState, {
      type: "open",
      threadId: "t1",
      earlierHidden: false,
      messages: [
        {
          id: "m1",
          role: "assistant",
          text: "",
          toolCalls: [],
          skipped: [{ name: "x", why }],
          runId: null,
          status: "needs_approval",
          failure: null,
          approval: null,
        },
      ],
    });
  const attach = (state: ChatState, messageId = "m1") =>
    chatReducer(state, { type: "attach_approval", messageId, payload });

  it("gives a waiting message its card, once", () => {
    const once = attach(opened("pending"));
    expect(once.messages[0]?.approval?.state).toBe("pending");
    const other = { ...payload, approval: { ...payload.approval, approval_id: "a2" } };
    const twice = chatReducer(once, { type: "attach_approval", messageId: "m1", payload: other });
    expect(twice.messages[0]?.approval?.payload.approval.approval_id).toBe("a1");
  });

  it("gives nothing to a message that is not waiting, or that is gone", () => {
    expect(attach(opened("rejected")).messages[0]?.approval).toBeNull();
    expect(attach(opened("pending"), "gone").messages[0]?.approval).toBeNull();
  });
});

describe("retryableText", () => {
  it("offers the last user message after a failed or stopped reply", () => {
    for (const status of ["failed", "stopped"] as const) {
      expect(retryableText(settled(sent("again"), status))).toBe("again");
    }
  });

  it("offers nothing while running, after success, or in an empty chat", () => {
    expect(retryableText(sent())).toBeNull();
    expect(retryableText(settled(sent(), "done"))).toBeNull();
    expect(retryableText(settled(sent(), "needs_approval"))).toBeNull();
    expect(retryableText(initialChatState)).toBeNull();
  });

  it("drop_last_turn removes the user message and the failed reply", () => {
    const state = chatReducer(sent(), { type: "drop_last_turn" });

    expect(state.messages).toEqual([]);
  });
});
