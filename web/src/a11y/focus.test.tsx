import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "@/App";
import { ChatScreen } from "@/features/chat/ChatScreen";
import { DataScreen } from "@/features/data/DataScreen";
import { AuthProvider } from "@/lib/auth";
import { AuthSession } from "@/lib/auth/session";
import { fakeApi, memory } from "@/test/dataApi";
import { CONFIG } from "@/test/oidc";
import { controlledStream, frame, jsonResponse, sseResponse, streamOf } from "@/test/sse";

import indexHtml from "../../index.html?raw";

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
  used_tools: [],
  confidence: 1,
  refused: false,
  clarification_needed: false,
});
const reply = (answer: string) =>
  sseResponse(
    streamOf([
      started,
      frame("token", { text: answer }),
      frame("final", final(answer)),
      frame("done", {}),
    ]),
  );

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

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

const composer = () => screen.getByRole("textbox", { name: "Message" });

describe("keyboard-only use", () => {
  it("reaches every control of the signed-in app in a sensible order", async () => {
    const session = new AuthSession({ config: CONFIG });
    vi.spyOn(session, "getSnapshot").mockReturnValue({
      status: "signed_in",
      displayName: "alice",
      error: null,
    });
    vi.spyOn(session, "init").mockResolvedValue();
    vi.spyOn(session, "getAccessToken").mockReturnValue("tok-1");
    const user = userEvent.setup();
    render(
      <AuthProvider session={session}>
        <App apiUrl={API} maxChars={12_000} />
      </AuthProvider>,
    );
    const expected = [
      screen.getByRole("button", { name: "Sign out" }),
      screen.getByRole("button", { name: "Chat" }),
      screen.getByRole("button", { name: "Your data" }),
      screen.getByRole("button", { name: "New conversation" }),
      composer(),
    ];
    const order: (Element | null)[] = [];
    for (let i = 0; i < expected.length; i += 1) {
      await user.tab();
      order.push(document.activeElement);
    }

    expect(order).toEqual(expected);
  });

  it("holds a whole conversation with an approval without a pointer", async () => {
    const fetchMock = vi.fn<typeof fetch>();
    fetchMock
      .mockResolvedValueOnce(
        sseResponse(
          streamOf([
            started,
            frame("token", { text: "I will note that." }),
            frame("approval_required", approval),
            frame("done", {}),
          ]),
        ),
      )
      .mockResolvedValueOnce(reply("Noted."));
    chat(fetchMock);
    const user = userEvent.setup();
    await user.tab(); // New conversation
    await user.tab(); // the composer
    expect(composer()).toHaveFocus();
    await user.keyboard("remember I like tea{Enter}");

    // The approval card takes focus when it appears, so the user knows a decision waits.
    const heading = await screen.findByRole("heading", { name: "Approval needed" });
    await waitFor(() => {
      expect(heading).toHaveFocus();
    });

    await user.tab();
    expect(screen.getByRole("button", { name: "Approve" })).toHaveFocus();
    await user.keyboard("{Enter}");

    expect(await screen.findByText("Noted.")).toBeInTheDocument();
    // The decided card's buttons are gone; focus returns to the composer, not to the page.
    await waitFor(() => {
      expect(composer()).toHaveFocus();
    });
  });

  it("rejects with the keyboard too", async () => {
    const fetchMock = vi.fn<typeof fetch>();
    fetchMock
      .mockResolvedValueOnce(
        sseResponse(streamOf([started, frame("approval_required", approval), frame("done", {})])),
      )
      .mockResolvedValueOnce(reply("Ok, not saved."));
    chat(fetchMock);
    const user = userEvent.setup();
    await user.click(composer());
    await user.keyboard("remember{Enter}");
    await screen.findByRole("heading", { name: "Approval needed" });
    await user.tab();
    await user.tab();
    expect(screen.getByRole("button", { name: "Reject" })).toHaveFocus();
    await user.keyboard(" ");

    expect(await screen.findByText("You rejected this.")).toBeInTheDocument();
  });
});

describe("focus after a reply", () => {
  it("returns to the composer when the user stops a reply with the keyboard", async () => {
    const { stream, push } = controlledStream();
    chat(vi.fn<typeof fetch>().mockResolvedValue(sseResponse(stream)));
    const user = userEvent.setup();
    await user.click(composer());
    await user.keyboard("hello{Enter}");
    push(started);
    push(frame("token", { text: "partial" }));
    await screen.findByText("partial");
    screen.getByRole("button", { name: "Stop" }).focus();
    await user.keyboard("{Enter}");

    await screen.findByText("Stopped.");
    expect(composer()).toHaveFocus();
  });

  it("keeps the user in the composer after clicking Send, though Send disables itself", async () => {
    const { stream, push } = controlledStream();
    chat(vi.fn<typeof fetch>().mockResolvedValue(sseResponse(stream)));
    const user = userEvent.setup();
    await user.click(composer());
    await user.paste("hello");
    await user.click(screen.getByRole("button", { name: "Send" }));

    // While the reply is still streaming, focus is not stranded on the now-disabled button.
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    expect(composer()).toHaveFocus();
    push(started);
    push(frame("final", final("done")));
    push(frame("done", {}));
    await screen.findByText("done");
    expect(composer()).toHaveFocus();
  });

  it("does not steal focus the user has moved elsewhere", async () => {
    const { stream, push } = controlledStream();
    chat(vi.fn<typeof fetch>().mockResolvedValue(sseResponse(stream)));
    const user = userEvent.setup();
    await user.click(composer());
    await user.keyboard("hello{Enter}");
    push(started);
    const elsewhere = screen.getByRole("button", { name: "New conversation" });
    elsewhere.focus();
    push(frame("final", final("all done")));
    push(frame("done", {}));
    await screen.findByText("all done");

    expect(elsewhere).toHaveFocus();
  });

  it("puts focus in the composer for a new conversation", async () => {
    chat(vi.fn<typeof fetch>().mockResolvedValue(reply("hi")));
    const user = userEvent.setup();
    await user.click(composer());
    await user.keyboard("hello{Enter}");
    await screen.findByText("hi");
    await user.click(screen.getByRole("button", { name: "New conversation" }));

    expect(composer()).toHaveFocus();
    expect(screen.queryByText("hi")).toBeNull();
  });

  it("announces a failure without moving focus off the composer", async () => {
    chat(
      vi
        .fn<typeof fetch>()
        .mockResolvedValue(jsonResponse(429, { detail: "rate_limited" }, { "Retry-After": "3" })),
    );
    const user = userEvent.setup();
    await user.click(composer());
    await user.keyboard("hello{Enter}");

    expect(await screen.findByRole("alert")).toHaveTextContent("Try again in 3 seconds.");
    await waitFor(() => {
      expect(composer()).toHaveFocus();
    });
  });
});

describe("focus when deleting a memory", () => {
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

  it("moves to Confirm, back to Delete on Cancel, and to the heading after the memory is gone", async () => {
    data(
      fakeApi({ memories: [memory(1, "likes tea"), memory(2, "likes coffee")], threads: [] }).fetch,
    );
    const user = userEvent.setup();
    const first = (await screen.findByText("likes tea")).closest("li");
    if (first === null) throw new Error("no item");
    const deleteFirst = () => first.querySelector("button");

    deleteFirst()?.focus();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("button", { name: "Confirm delete" })).toHaveFocus();

    await user.keyboard("{Tab}{Enter}"); // Cancel
    await waitFor(() => {
      expect(deleteFirst()).toHaveFocus();
    });

    await user.keyboard("{Enter}");
    await user.keyboard("{Enter}"); // Confirm delete
    await waitFor(() => {
      expect(screen.queryByText("likes tea")).toBeNull();
    });
    expect(screen.getByRole("heading", { name: "Memories" })).toHaveFocus();
  });

  it("returns to the memory's Delete button when the delete fails", async () => {
    const api = fakeApi({ memories: [memory(1, "likes tea")], threads: [] });
    const failing: typeof fetch = (input, init) =>
      init?.method === "DELETE"
        ? Promise.resolve(jsonResponse(500, { detail: "internal_server_error" }))
        : api.fetch(input, init);
    data(failing);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "Confirm delete" }));

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Delete" })).toHaveFocus();
    });
  });
});

describe("layout and colour scheme", () => {
  it("lets the page scale to the screen and zoom, and declares light and dark support", () => {
    expect(indexHtml).toMatch(
      /<meta name="viewport" content="width=device-width, initial-scale=1\.0" \/>/,
    );
    expect(indexHtml).not.toMatch(/maximum-scale|user-scalable/);
    expect(indexHtml).toMatch(/<meta name="color-scheme" content="light dark" \/>/);
  });
});
