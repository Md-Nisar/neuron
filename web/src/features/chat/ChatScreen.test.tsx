import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { controlledStream, frame, jsonResponse, sseResponse, streamOf } from "@/test/sse";

import { ChatScreen } from "./ChatScreen";

const API = "http://127.0.0.1:8000";

const final = (answer: string, threadId = "t1") => ({
  status: "completed",
  request_id: "r1",
  thread_id: threadId,
  answer,
  used_tools: [],
  confidence: 1,
  refused: false,
  clarification_needed: false,
});
const started = (threadId = "t1") =>
  frame("run_started", { request_id: "r1", thread_id: threadId });

/** A complete, successful reply. */
const reply = (answer: string, threadId = "t1") =>
  sseResponse(
    streamOf([
      started(threadId),
      frame("token", { text: answer }),
      frame("final", final(answer, threadId)),
      frame("done", {}),
    ]),
  );

type FetchMock = ReturnType<typeof vi.fn<typeof fetch>>;

function setup(options: { token?: string | null; maxChars?: number } = {}) {
  const fetchMock: FetchMock = vi.fn<typeof fetch>();
  const onSessionEnded = vi.fn();
  const user = userEvent.setup();
  const view = render(
    <ChatScreen
      apiUrl={API}
      maxChars={options.maxChars ?? 12_000}
      getAccessToken={() => (options.token === undefined ? "tok-1" : options.token)}
      onSessionEnded={onSessionEnded}
      fetch={fetchMock}
    />,
  );
  const box = () => screen.getByRole("textbox", { name: "Message" });
  const paste = async (text: string) => {
    await user.click(box());
    await user.paste(text);
  };
  const say = async (text: string) => {
    await paste(text);
    await user.click(screen.getByRole("button", { name: "Send" }));
  };
  const bodyOf = (call: number): Record<string, unknown> => {
    const body = fetchMock.mock.calls[call]?.[1]?.body;
    return typeof body === "string" ? (JSON.parse(body) as Record<string, unknown>) : {};
  };
  return { fetchMock, onSessionEnded, user, view, box, paste, say, bodyOf };
}

describe("sending and streaming", () => {
  it("shows the preview as it streams, then replaces it with the final answer", async () => {
    const { fetchMock, say } = setup();
    const { stream, push } = controlledStream();
    fetchMock.mockResolvedValueOnce(sseResponse(stream));
    await say("What is 19 * 3?");

    push(started());
    push(frame("token", { text: "5" }));
    push(frame("token", { text: "7 (draft" }));
    expect(await screen.findByText("57 (draft")).toBeInTheDocument();

    push(frame("final", final("The answer is 57.")));
    push(frame("done", {}));
    expect(await screen.findByText("The answer is 57.")).toBeInTheDocument();
    expect(screen.queryByText("57 (draft")).toBeNull();
    expect(screen.getByText("What is 19 * 3?")).toBeInTheDocument();
  });

  it("sends the token in a header and the thread id on the next message", async () => {
    const { fetchMock, say, bodyOf } = setup();
    fetchMock
      .mockResolvedValueOnce(reply("one", "thread-9"))
      .mockResolvedValueOnce(reply("two", "thread-9"));
    await say("first");
    await screen.findByText("one");
    await say("second");
    await screen.findByText("two");

    expect(bodyOf(0)).toEqual({ message: "first" });
    expect(bodyOf(1)).toEqual({ message: "second", thread_id: "thread-9" });
    expect(fetchMock.mock.calls[0]?.[1]?.headers).toMatchObject({ Authorization: "Bearer tok-1" });
  });

  it("lists the tools the reply used, as text", async () => {
    const { fetchMock, say } = setup();
    fetchMock.mockResolvedValueOnce(
      sseResponse(
        streamOf([
          started(),
          frame("tool_call", { name: "calculator" }),
          frame("final", final("57")),
          frame("done", {}),
        ]),
      ),
    );
    await say("19*3");

    expect(await screen.findByText("Used: calculator")).toBeInTheDocument();
  });

  it("sends once even if Send is pressed again while the reply is streaming", async () => {
    const { fetchMock, say, paste, user } = setup();
    fetchMock.mockResolvedValueOnce(sseResponse(controlledStream().stream));
    await say("hello");
    await paste("again");

    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    await user.keyboard("{Enter}");
    expect(fetchMock).toHaveBeenCalledOnce();
  });
});

describe("stop and retry", () => {
  it("stops, keeps the partial answer, and retry resends the same message without duplicating it", async () => {
    let cancelled = false;
    const { fetchMock, say, user, bodyOf } = setup();
    const { stream, push } = controlledStream(() => (cancelled = true));
    fetchMock
      .mockResolvedValueOnce(sseResponse(stream))
      .mockResolvedValueOnce(reply("full answer"));
    await say("tell me more");
    push(started());
    push(frame("token", { text: "partial text" }));
    await screen.findByText("partial text");
    await user.click(screen.getByRole("button", { name: "Stop" }));

    expect(await screen.findByText("Stopped.")).toBeInTheDocument();
    expect(screen.getByText("partial text")).toBeInTheDocument();
    expect(cancelled).toBe(true);

    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("full answer")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(bodyOf(1).message).toBe("tell me more");
    expect(screen.getAllByText("You")).toHaveLength(1);
    expect(screen.queryByText("partial text")).toBeNull();
  });

  it("keeps the partial answer when the connection breaks and offers retry", async () => {
    const { fetchMock, say } = setup();
    fetchMock.mockResolvedValueOnce(
      sseResponse(
        streamOf([started(), frame("token", { text: "half an ans" })], new TypeError("reset")),
      ),
    );
    await say("question");

    expect(await screen.findByText("half an ans")).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The connection was lost before the reply finished.",
    );
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("shows a server error with fixed wording, keeping what streamed", async () => {
    const { fetchMock, say } = setup();
    fetchMock.mockResolvedValueOnce(
      sseResponse(
        streamOf([
          started(),
          frame("token", { text: "so far" }),
          frame("error", { code: "model_unavailable", retryable: true }),
          frame("done", {}),
        ]),
      ),
    );
    await say("question");

    expect(await screen.findByText("so far")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("The reply failed. Try again.");
  });
});

describe("errors before the stream starts", () => {
  it.each([
    [403, { detail: "authorization_error" }, {}, "You do not have permission to do that."],
    [
      404,
      { detail: "thread_not_found" },
      {},
      "That conversation could not be found. Start a new conversation.",
    ],
    [
      409,
      { detail: "thread_busy" },
      {},
      "The previous reply is still finishing. Try again in a moment.",
    ],
    [
      409,
      { detail: "approval_pending" },
      {},
      "A tool call is waiting for your approval. Decide it before sending more.",
    ],
    [
      429,
      { detail: "rate_limited" },
      { "Retry-After": "7" },
      "Too many requests. Try again in 7 seconds.",
    ],
    [
      429,
      { detail: "rate_limited" },
      { "Retry-After": "1" },
      "Too many requests. Try again in 1 second.",
    ],
    [400, { detail: "validation_error" }, {}, "That message was rejected. Check it and try again."],
    [
      500,
      { detail: "internal_server_error" },
      {},
      "Something went wrong on the server. Try again.",
    ],
    [
      503,
      { detail: "shutting_down" },
      { "Retry-After": "1" },
      "The service is unavailable right now. Try again shortly.",
    ],
  ])(
    "HTTP %i shows fixed wording and keeps the message for retry",
    async (status, body, headers, text) => {
      const { fetchMock, say } = setup();
      fetchMock.mockResolvedValueOnce(jsonResponse(status, body, headers));
      await say("hello");

      expect(await screen.findByRole("alert")).toHaveTextContent(text);
      expect(screen.getByText("hello")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
    },
  );

  it("401 ends the session and asks the app to sign in again", async () => {
    const { fetchMock, say, onSessionEnded } = setup();
    fetchMock.mockResolvedValueOnce(jsonResponse(401, { detail: "authentication_error" }));
    await say("hello");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Your session ended. Please sign in again.",
    );
    expect(onSessionEnded).toHaveBeenCalledOnce();
  });

  it("does not call the API without a token", async () => {
    const { fetchMock, say, onSessionEnded } = setup({ token: null });
    await say("hello");

    expect(await screen.findByRole("alert")).toHaveTextContent("Your session ended.");
    expect(fetchMock).not.toHaveBeenCalled();
    expect(onSessionEnded).toHaveBeenCalledOnce();
  });

  it("shows a network failure", async () => {
    const { fetchMock, say } = setup();
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await say("hello");

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not reach the server.");
  });

  it("never shows free-form server text", async () => {
    const { fetchMock, say } = setup();
    fetchMock.mockResolvedValueOnce(
      jsonResponse(500, { detail: "Traceback: password=hunter2 in /srv/app.py" }),
    );
    await say("hello");

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).not.toContain("hunter2");
  });
});

describe("approval", () => {
  it("shows a fixed notice, not the model's wording, and keeps what was said before", async () => {
    const { fetchMock, say } = setup();
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
    fetchMock.mockResolvedValueOnce(
      sseResponse(
        streamOf([
          started(),
          frame("token", { text: "I will note that." }),
          frame("approval_required", approval),
          frame("done", {}),
        ]),
      ),
    );
    await say("remember I like tea");

    expect(await screen.findByRole("status")).toHaveTextContent("waiting for your approval");
    expect(screen.getByText("I will note that.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /approve|reject/i })).toBeNull();
  });
});

describe("composer", () => {
  it("disables Send for an empty message and counts characters", async () => {
    const { paste } = setup();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    await paste("hello");

    expect(screen.getByRole("button", { name: "Send" })).toBeEnabled();
    expect(screen.getByText("5 / 12000")).toBeInTheDocument();
  });

  it("refuses a message over the limit without sending it", async () => {
    const { fetchMock, say } = setup({ maxChars: 100 });
    await say("x".repeat(101));

    expect(await screen.findByRole("alert")).toHaveTextContent("The limit is 100 characters.");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("refuses control characters without sending", async () => {
    const { fetchMock, say } = setup();
    await say("a\u0007b");

    expect(await screen.findByRole("alert")).toHaveTextContent("characters that cannot be sent");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("sends on Enter and inserts a line break on Shift+Enter", async () => {
    const { fetchMock, user, box } = setup();
    fetchMock.mockResolvedValueOnce(reply("ok"));
    await user.click(box());
    await user.keyboard("a{Shift>}{Enter}{/Shift}b");

    expect(box()).toHaveValue("a\nb");
    expect(fetchMock).not.toHaveBeenCalled();
    await user.keyboard("{Enter}");
    await screen.findByText("ok");
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("clears the composer after sending", async () => {
    const { fetchMock, say, box } = setup();
    fetchMock.mockResolvedValueOnce(reply("ok"));
    await say("hello");

    await waitFor(() => {
      expect(box()).toHaveValue("");
    });
  });
});

describe("new conversation", () => {
  it("clears the messages, forgets the thread, and aborts a running reply", async () => {
    let cancelled = false;
    const { fetchMock, say, user, bodyOf } = setup();
    fetchMock.mockResolvedValueOnce(reply("first", "old-thread"));
    await say("one");
    await screen.findByText("first");

    const { stream, push } = controlledStream(() => (cancelled = true));
    fetchMock.mockResolvedValueOnce(sseResponse(stream));
    await say("two");
    push(started("old-thread"));
    await user.click(screen.getByRole("button", { name: "New conversation" }));

    expect(screen.queryByText("one")).toBeNull();
    expect(screen.queryByText("first")).toBeNull();
    await waitFor(() => {
      expect(cancelled).toBe(true);
    });

    fetchMock.mockResolvedValueOnce(reply("fresh", "new-thread"));
    await say("three");
    await screen.findByText("fresh");
    expect(bodyOf(2)).toEqual({ message: "three" });
  });

  it("aborts the stream when the screen goes away", async () => {
    let cancelled = false;
    const { fetchMock, say, view } = setup();
    fetchMock.mockResolvedValueOnce(sseResponse(controlledStream(() => (cancelled = true)).stream));
    await say("hello");
    view.unmount();

    await waitFor(() => {
      expect(cancelled).toBe(true);
    });
  });
});

describe("hostile content", () => {
  it("renders model and user markup as text and creates no active elements", async () => {
    const hostile =
      '<img src=x onerror="alert(1)"><script>alert(2)</script> **bold** [click](javascript:alert(3)) ![t](https://evil.example/p.png)';
    const { fetchMock, say, view } = setup();
    fetchMock.mockResolvedValueOnce(
      sseResponse(
        streamOf([
          started(),
          frame("token", { text: hostile }),
          frame("final", final(hostile)),
          frame("done", {}),
        ]),
      ),
    );
    await say("<script>alert(4)</script>");

    expect(await screen.findByText("bold")).toBeInTheDocument();
    expect(screen.getByText("<script>alert(4)</script>")).toBeInTheDocument();
    expect(view.container.querySelector("img, script, iframe, a, [onerror]")).toBeNull();
    expect(view.container.textContent).toContain('<img src=x onerror="alert(1)">');
  });
});
