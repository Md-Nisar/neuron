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
