import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { controlledStream, frame, sseResponse, streamOf } from "@/test/sse";

import { useChat } from "./useChat";

const approval = {
  status: "approval_required",
  request_id: "r1",
  thread_id: "t1",
  approval: {
    approval_id: "a1",
    actions: [{ name: "remember", args: { text: "likes tea" } }],
    allowed_decisions: ["approve", "reject"],
  },
};
const started = frame("run_started", { request_id: "r1", thread_id: "t1" });

describe("narrowing to chosen knowledge bases", () => {
  const A = "0b6f1c1e-6c8e-4c36-9d2b-6a1f2f3e4d5c";
  const body = (call: Parameters<typeof fetch> | undefined) =>
    JSON.parse(call?.[1]?.body as string) as Record<string, unknown>;

  it("sends the chosen ids with the question and again with the decision, and none when unset", async () => {
    const fetchMock = vi.fn<typeof fetch>();
    fetchMock.mockResolvedValueOnce(
      sseResponse(streamOf([started, frame("approval_required", approval), frame("done", {})])),
    );
    fetchMock.mockResolvedValue(sseResponse(streamOf([started, frame("done", {})])));
    const { result } = renderHook(() =>
      useChat({
        apiUrl: "http://127.0.0.1:8000",
        getAccessToken: () => "tok",
        onSessionEnded: vi.fn(),
        maxChars: 1000,
        fetch: fetchMock,
      }),
    );
    act(() => {
      result.current.setKnowledgeBaseIds([A]);
    });
    await act(async () => {
      await result.current.send("what does the policy say?");
    });
    const messageId = result.current.messages.find((m) => m.approval !== null)?.id ?? "";
    await act(async () => {
      await result.current.decide(messageId, "approve");
    });
    act(() => {
      result.current.setKnowledgeBaseIds([]);
    });
    await act(async () => {
      await result.current.send("and now?");
    });

    expect(body(fetchMock.mock.calls[0])["knowledge_base_ids"]).toEqual([A]);
    expect(body(fetchMock.mock.calls[1])).toEqual({ decision: "approve", knowledge_base_ids: [A] });
    expect(body(fetchMock.mock.calls[2])).not.toHaveProperty("knowledge_base_ids");
  });
});

describe("useChat.decide", () => {
  it("makes one decision even if called twice in the same tick", async () => {
    const fetchMock = vi.fn<typeof fetch>();
    fetchMock.mockResolvedValueOnce(
      sseResponse(streamOf([started, frame("approval_required", approval), frame("done", {})])),
    );
    fetchMock.mockResolvedValueOnce(sseResponse(controlledStream().stream));
    const { result } = renderHook(() =>
      useChat({
        apiUrl: "http://127.0.0.1:8000",
        getAccessToken: () => "tok",
        onSessionEnded: vi.fn(),
        maxChars: 1000,
        fetch: fetchMock,
      }),
    );
    await act(async () => {
      await result.current.send("remember I like tea");
    });
    const messageId = result.current.messages.find((m) => m.approval !== null)?.id ?? "";
    expect(messageId).not.toBe("");

    // Both calls see the same render's state: only the synchronous guard can stop the second.
    await act(async () => {
      void result.current.decide(messageId, "approve");
      void result.current.decide(messageId, "approve");
      await Promise.resolve();
    });

    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("ignores a decision the server did not offer", async () => {
    const fetchMock = vi.fn<typeof fetch>();
    const onlyReject = {
      ...approval,
      approval: { ...approval.approval, allowed_decisions: ["reject"] },
    };
    fetchMock.mockResolvedValueOnce(
      sseResponse(streamOf([started, frame("approval_required", onlyReject), frame("done", {})])),
    );
    const { result } = renderHook(() =>
      useChat({
        apiUrl: "http://127.0.0.1:8000",
        getAccessToken: () => "tok",
        onSessionEnded: vi.fn(),
        maxChars: 1000,
        fetch: fetchMock,
      }),
    );
    await act(async () => {
      await result.current.send("hello");
    });
    const messageId = result.current.messages.find((m) => m.approval !== null)?.id ?? "";
    await act(async () => {
      await result.current.decide(messageId, "approve");
    });

    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("ignores a message that has no approval", async () => {
    const fetchMock = vi.fn<typeof fetch>();
    const { result } = renderHook(() =>
      useChat({
        apiUrl: "http://127.0.0.1:8000",
        getAccessToken: () => "tok",
        onSessionEnded: vi.fn(),
        maxChars: 1000,
        fetch: fetchMock,
      }),
    );
    await act(async () => {
      await result.current.decide("no-such-message", "approve");
    });

    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("useChat.open", () => {
  const history = (): Response =>
    new Response(
      JSON.stringify({ messages: [{ role: "user", content: "hi", tool_calls: [] }], total: 1 }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  const hook = (fetchMock: typeof fetch) =>
    renderHook(() =>
      useChat({
        apiUrl: "http://127.0.0.1:8000",
        getAccessToken: () => "tok",
        onSessionEnded: vi.fn(),
        maxChars: 1000,
        fetch: fetchMock,
      }),
    );

  it("loads once if called twice in the same tick", async () => {
    const fetchMock = vi.fn<typeof fetch>(() => Promise.resolve(history()));
    const { result } = hook(fetchMock);
    await act(async () => {
      await Promise.all([result.current.open("t1"), result.current.open("t1")]);
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(result.current.threadId).toBe("t1");
  });

  it("does nothing while a reply is streaming", async () => {
    const fetchMock = vi.fn<typeof fetch>();
    fetchMock.mockResolvedValueOnce(sseResponse(controlledStream().stream));
    const { result } = hook(fetchMock);
    await act(async () => {
      void result.current.send("hello");
      await Promise.resolve();
    });
    await act(async () => {
      await result.current.open("t1");
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
