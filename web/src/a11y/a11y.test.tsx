import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "@/App";
import { ChatScreen } from "@/features/chat/ChatScreen";
import { DataScreen } from "@/features/data/DataScreen";
import { ThreadList } from "@/features/threads/ThreadList";
import { AuthProvider } from "@/lib/auth";
import { AuthSession, type AuthSnapshot } from "@/lib/auth/session";
import { accessibilityViolations } from "@/test/axe";
import { fakeApi, memory, thread } from "@/test/dataApi";
import { CONFIG } from "@/test/oidc";
import { frame, jsonResponse, sseResponse, streamOf } from "@/test/sse";

const API = "http://127.0.0.1:8000";
const started = frame("run_started", { request_id: "r1", thread_id: "t1" });
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
const final = (answer: string) => ({
  status: "completed",
  request_id: "r2",
  thread_id: "t1",
  answer,
  used_tools: ["calculator"],
  confidence: 1,
  refused: false,
  clarification_needed: false,
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function appWith(snapshot: AuthSnapshot) {
  const session = new AuthSession({ config: CONFIG });
  vi.spyOn(session, "getSnapshot").mockReturnValue(snapshot);
  vi.spyOn(session, "init").mockResolvedValue();
  vi.spyOn(session, "getAccessToken").mockReturnValue("tok-1");
  return render(
    <AuthProvider session={session}>
      <App apiUrl={API} maxChars={12_000} />
    </AuthProvider>,
  );
}

function chat(fetchImpl: typeof fetch) {
  return render(
    <ChatScreen
      apiUrl={API}
      maxChars={12_000}
      getAccessToken={() => "tok-1"}
      onSessionEnded={vi.fn()}
      fetch={fetchImpl}
    />,
  );
}

async function say(text: string) {
  const user = userEvent.setup();
  await user.click(screen.getByRole("textbox", { name: "Message" }));
  await user.paste(text);
  await user.click(screen.getByRole("button", { name: "Send" }));
  return user;
}

describe("sign-in states have no accessibility violations", () => {
  it.each<[string, AuthSnapshot]>([
    ["loading", { status: "loading", displayName: null, error: null }],
    ["signed out", { status: "signed_out", displayName: null, error: null }],
    ["session expired", { status: "expired", displayName: null, error: null }],
    ["a sign-in error", { status: "error", displayName: null, error: "state_mismatch" }],
  ])("%s", async (_name, snapshot) => {
    appWith(snapshot);

    expect(await accessibilityViolations()).toEqual([]);
  });
});

describe("the chat has no accessibility violations", () => {
  it("when empty and signed in", async () => {
    appWith({ status: "signed_in", displayName: "alice", error: null });

    expect(await accessibilityViolations()).toEqual([]);
  });

  it("with a conversation: markdown, a list, code, a link, tool names and hostile text", async () => {
    const answer = [
      "## Result",
      "",
      "- one",
      "- two",
      "",
      "[docs](https://docs.example.org/x) and `code`",
      "",
      "```",
      "<script>alert(1)</script>",
      "```",
      "",
      "![tracker](https://evil.example/p.png)",
    ].join("\n");
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValue(
        sseResponse(
          streamOf([
            started,
            frame("tool_call", { name: "calculator" }),
            frame("token", { text: answer }),
            frame("final", final(answer)),
            frame("done", {}),
          ]),
        ),
      );
    chat(fetchMock);
    await say("What is 19 * 3?");
    await screen.findByText("Result");

    expect(await accessibilityViolations()).toEqual([]);
  });

  it("with a failed reply and a stopped one", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse(429, { detail: "rate_limited" }, { "Retry-After": "7" }));
    chat(fetchMock);
    await say("hello");
    await screen.findByRole("alert");

    expect(await accessibilityViolations()).toEqual([]);
  });

  it("with a draft over the limit", async () => {
    chat(vi.fn<typeof fetch>());
    await say("x".repeat(12_001));
    await screen.findByRole("alert");

    expect(await accessibilityViolations()).toEqual([]);
  });
});

describe("the approval card has no accessibility violations", () => {
  async function paused() {
    const fetchMock = vi.fn<typeof fetch>();
    fetchMock.mockResolvedValueOnce(
      sseResponse(
        streamOf([
          started,
          frame("token", { text: "I will note that." }),
          frame("approval_required", approval),
          frame("done", {}),
        ]),
      ),
    );
    chat(fetchMock);
    const user = await say("remember I like tea");
    await screen.findByRole("region", { name: "Approval required" });
    return { fetchMock, user };
  }

  it("while waiting for a decision", async () => {
    await paused();

    expect(await accessibilityViolations()).toEqual([]);
  });

  it("when the arguments are too long to approve", async () => {
    const long = {
      ...approval,
      approval: {
        ...approval.approval,
        actions: [{ name: "remember", args: { text: "x".repeat(5000) } }],
      },
    };
    chat(
      vi
        .fn<typeof fetch>()
        .mockResolvedValue(
          sseResponse(streamOf([started, frame("approval_required", long), frame("done", {})])),
        ),
    );
    await say("go");
    await screen.findByText(/too long to show in full/);

    expect(await accessibilityViolations()).toEqual([]);
  });

  it("after the decision, with the continuation", async () => {
    const { fetchMock, user } = await paused();
    fetchMock.mockResolvedValueOnce(
      sseResponse(
        streamOf([
          started,
          frame("token", { text: "Noted." }),
          frame("final", final("Noted.")),
          frame("done", {}),
        ]),
      ),
    );
    await user.click(screen.getByRole("button", { name: "Approve" }));
    await screen.findByText("Noted.");

    expect(await accessibilityViolations()).toEqual([]);
  });

  it("when the approval is no longer available", async () => {
    const { fetchMock, user } = await paused();
    fetchMock.mockResolvedValueOnce(jsonResponse(404, { detail: "approval_not_found" }));
    await user.click(screen.getByRole("button", { name: "Approve" }));
    await screen.findByText(/no longer available/);

    expect(await accessibilityViolations()).toEqual([]);
  });
});

describe("the data page has no accessibility violations", () => {
  function data(fetchImpl: typeof fetch) {
    return render(
      <DataScreen
        deps={{
          apiUrl: API,
          getAccessToken: () => "tok-1",
          onSessionEnded: vi.fn(),
          fetch: fetchImpl,
        }}
        onErased={vi.fn()}
      />,
    );
  }

  it("with memories", async () => {
    data(
      fakeApi({
        memories: [memory(1, "likes tea"), memory(2, "<b>bold</b>")],
        threads: [thread(1, 2)],
      }).fetch,
    );
    await screen.findByText("likes tea");

    expect(await accessibilityViolations()).toEqual([]);
  });

  it("with no memories, and when memory is off", async () => {
    data(fakeApi({ memories: [], threads: [], memoryEnabled: false }).fetch);
    await screen.findByText("Memory is turned off for this service.");

    expect(await accessibilityViolations()).toEqual([]);
  });

  it("while confirming a delete", async () => {
    data(fakeApi({ memories: [memory(1, "likes tea")], threads: [] }).fetch);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Delete" }));

    expect(await accessibilityViolations()).toEqual([]);
  });

  it("after an erase that skipped a busy conversation", async () => {
    data(fakeApi({ memories: [], threads: [thread(1, 1), thread(2, 1)], eraseSkipsBusy: 1 }).fetch);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/Type erase my data to confirm/), "erase my data");
    await user.click(screen.getByRole("button", { name: "Erase all my data" }));
    await waitFor(() => {
      expect(screen.getByText(/could not be erased/)).toBeInTheDocument();
    });

    expect(await accessibilityViolations()).toEqual([]);
  });
});

describe("the conversation list has no accessibility violations", () => {
  function list(fetchImpl: typeof fetch) {
    return render(
      <ThreadList
        deps={{
          apiUrl: API,
          getAccessToken: () => "tok-1",
          onSessionEnded: vi.fn(),
          fetch: fetchImpl,
        }}
        refresh={0}
        onDeleted={vi.fn()}
        onOpen={vi.fn()}
        activeThreadId={null}
        openDisabled={false}
      />,
    );
  }
  const titled = (n: number, title: string | null) => ({ ...thread(n, 2), title });

  it("with conversations, an untitled one and hostile titles", async () => {
    list(
      fakeApi({
        memories: [],
        threads: [titled(1, "Trip to Lisbon"), titled(2, null), titled(3, "<b>bold</b>")],
      }).fetch,
    );
    await screen.findByText("Trip to Lisbon");

    expect(await accessibilityViolations()).toEqual([]);
  });

  it("when empty, and when the list failed to load", async () => {
    const view = list(fakeApi({ memories: [], threads: [] }).fetch);
    await screen.findByText("No conversations yet.");
    expect(await accessibilityViolations()).toEqual([]);
    view.unmount();

    list(() => Promise.resolve(jsonResponse(500, {})));
    await screen.findByRole("alert");
    expect(await accessibilityViolations()).toEqual([]);
  });

  it("while renaming and while confirming a delete", async () => {
    list(fakeApi({ memories: [], threads: [titled(1, "Trip"), titled(2, "Other")] }).fetch);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Rename Trip" }));
    await user.click(screen.getByRole("button", { name: "Delete Other" }));

    expect(await accessibilityViolations()).toEqual([]);
  });
});
