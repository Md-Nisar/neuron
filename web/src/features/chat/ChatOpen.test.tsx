import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SignedInView } from "@/SignedInView";
import { fakeApi, thread, type FakeMessage, type FakeThread } from "@/test/dataApi";
import { frame, jsonResponse, sseResponse, streamOf } from "@/test/sse";

const ID = thread(1, 0).thread_id;
const RLO = String.fromCodePoint(0x202e);

const say = (role: "user" | "assistant", content: string, calls: FakeMessage["tool_calls"] = []) =>
  ({ role, content, tool_calls: calls }) satisfies FakeMessage;

function conversation(messages: FakeMessage[], extra: Partial<FakeThread> = {}): FakeThread {
  return { ...thread(1, 0), title: "Past chat", messages, ...extra };
}

type Intercept = (method: string, url: URL, init?: RequestInit) => Promise<Response | undefined>;

function setup(threads: FakeThread[], intercept?: Intercept) {
  const api = fakeApi({ memories: [], threads });
  const sessionEnded = vi.fn();
  const posted: { path: string; body: unknown }[] = [];
  const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
    const url = new URL(input instanceof URL ? input.href : (input as string));
    const method = init?.method ?? "GET";
    const hijacked = await intercept?.(method, url, init);
    if (hijacked !== undefined) return hijacked;
    if (method === "POST") {
      posted.push({
        path: url.pathname,
        body: JSON.parse(typeof init?.body === "string" ? init.body : "{}") as unknown,
      });
      const answer = url.pathname.endsWith("/stream") ? "continued" : "";
      return sseResponse(
        streamOf([
          frame("run_started", { request_id: "r9", thread_id: ID }),
          frame("token", { text: answer }),
          frame("final", {
            status: "completed",
            request_id: "r9",
            thread_id: ID,
            answer,
            used_tools: [],
            confidence: 1,
            refused: false,
            clarification_needed: false,
          }),
          frame("done", {}),
        ]),
      );
    }
    return api.fetch(input, init);
  });
  vi.stubGlobal("fetch", fetchMock);
  render(
    <SignedInView
      auth={{
        displayName: "alice",
        getAccessToken: () => "tok-1",
        sessionEnded,
        signOut: vi.fn(),
      }}
      apiUrl="http://127.0.0.1:8000"
      maxChars={12_000}
    />,
  );
  const open = async (title = "Past chat") => {
    await userEvent.click(await screen.findByRole("button", { name: `Open ${title}` }));
  };
  return { api, sessionEnded, posted, open, user: userEvent.setup() };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("opening a conversation", () => {
  it("shows its history, marks it current, focuses the composer and continues it", async () => {
    const { open, posted, user } = setup([
      conversation([say("user", "What is 2+2?"), say("assistant", "It is **4**.")]),
    ]);
    await open();

    expect(await screen.findByText("What is 2+2?")).toBeInTheDocument();
    expect(screen.getByText("4", { selector: "strong" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open Past chat" })).toHaveAttribute(
      "aria-current",
      "true",
    );
    await waitFor(() => {
      expect(screen.getByRole("textbox", { name: "Message" })).toHaveFocus();
    });

    await user.paste("and 3+3?");
    await user.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByText("continued");
    expect(posted).toEqual([
      { path: "/v1/agent/stream", body: { message: "and 3+3?", thread_id: ID } },
    ]);
  });

  it("offers no rating on an answer from an earlier session", async () => {
    const { open } = setup([conversation([say("user", "hi"), say("assistant", "hello")])]);
    await open();

    await screen.findByText("hello");
    expect(screen.queryByRole("button", { name: "Helpful" })).not.toBeInTheDocument();
  });

  it("shows what the server recorded for each tool call", async () => {
    const { open } = setup([
      conversation([
        say("user", "do things"),
        say("assistant", "Done.", [
          { name: "calculator", summary: "expression=2+2", status: "completed" },
          { name: "note_taker", summary: "text=milk", status: "rejected" },
          { name: "fetch_url", summary: "url=x", status: "failed" },
        ]),
      ]),
    ]);
    await open();

    expect(await screen.findByText("Used: calculator")).toBeInTheDocument();
    expect(screen.getByText("You rejected: note_taker")).toBeInTheDocument();
    expect(screen.getByText("Could not run: fetch_url")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Approval required" })).not.toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("expression=2+2");
  });

  it("renders hostile history as text and marks invisible characters in tool names", async () => {
    const { open } = setup([
      conversation([
        say("user", '<img src=x onerror="alert(1)">'),
        say("assistant", "<script>alert(2)</script> ![beacon](https://evil.example/p.png)", [
          { name: `gnp${RLO}.exe`, summary: "", status: "rejected" },
        ]),
      ]),
    ]);
    await open();

    expect(await screen.findByText('<img src=x onerror="alert(1)">')).toBeInTheDocument();
    expect(document.querySelector("img, script")).toBeNull();
    expect(screen.getByText("You rejected: gnp[U+202E].exe")).toBeInTheDocument();
  });

  it("shows only the latest page of a long conversation, and says so", async () => {
    const messages = Array.from({ length: 150 }, (_, i) =>
      say(i % 2 === 0 ? "user" : "assistant", `message ${String(i)}`),
    );
    const { open, api } = setup([conversation(messages)]);
    await open();

    expect(await screen.findByText("message 149")).toBeInTheDocument();
    expect(screen.getByText("message 50")).toBeInTheDocument();
    expect(screen.queryByText("message 49")).not.toBeInTheDocument();
    expect(screen.getByText("Earlier messages are not shown.")).toBeInTheDocument();
    const reads = api.calls.filter((call) => call.url.pathname.endsWith("/messages"));
    expect(reads.map((call) => call.url.search)).toEqual([
      "?limit=100&offset=0",
      "?limit=100&offset=50",
    ]);
  });
});

describe("a conversation that ended waiting for approval", () => {
  const paused = (extra: Partial<FakeThread> = {}) =>
    conversation(
      [
        say("user", "remember milk"),
        say("assistant", "", [{ name: "note_taker", summary: "text=milk", status: "pending" }]),
      ],
      {
        pending: {
          approval_id: "appr-1",
          actions: [{ name: "note_taker", args: { text: "milk" } }],
        },
        ...extra,
      },
    );

  it("shows the card from the server's copy of the request and decides it", async () => {
    const { open, user, posted } = setup([paused()]);
    await open();

    const card = await screen.findByRole("region", { name: "Approval required" });
    expect(within(card).getByText(/note_taker/)).toBeInTheDocument();
    expect(card).toHaveTextContent('"text": "milk"');
    await user.click(within(card).getByRole("button", { name: /Approve/ }));

    expect(await screen.findByText("continued")).toBeInTheDocument();
    expect(posted).toEqual([
      { path: `/v1/threads/${ID}/approvals/appr-1/stream`, body: { decision: "approve" } },
    ]);
  });

  it("shows only a notice when the approval is gone, and cannot be decided", async () => {
    const { open } = setup([paused({ pending: undefined })]);
    await open();

    expect(await screen.findByText("Waiting for approval: note_taker")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Approval required" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Approve/ })).not.toBeInTheDocument();
  });

  it("never shows a card the server addressed to another thread", async () => {
    const { open } = setup([
      paused({
        pending: {
          approval_id: "appr-1",
          thread_id: "99999999-9999-4999-8999-999999999999",
          actions: [{ name: "note_taker", args: { text: "evil" } }],
        },
      }),
    ]);
    await open();

    expect(await screen.findByText("Waiting for approval: note_taker")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Approval required" })).not.toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("evil");
  });

  it("does not put a card on a conversation that is not waiting, whatever the server says", async () => {
    const done = conversation([say("user", "hi"), say("assistant", "hello")], {
      pending: { approval_id: "stale", actions: [{ name: "note_taker", args: {} }] },
    });
    const { open, api } = setup([done]);
    await open();

    await screen.findByText("hello");
    expect(screen.queryByRole("region", { name: "Approval required" })).not.toBeInTheDocument();
    expect(api.calls.some((call) => call.url.pathname.endsWith("/approval"))).toBe(false);
  });
});

describe("when opening fails", () => {
  it("shows a fixed message and leaves the current chat alone", async () => {
    const { open, user } = setup([conversation([say("user", "x")])], (_m, url) =>
      Promise.resolve(
        url.pathname.endsWith("/messages")
          ? jsonResponse(404, { detail: "thread_not_found" })
          : undefined,
      ),
    );
    await user.click(await screen.findByRole("textbox", { name: "Message" }));
    await user.paste("draft stays");
    await open();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "That conversation could not be found. Start a new conversation.",
    );
    expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue("draft stays");
  });

  it("ends the session on a 401", async () => {
    const { open, sessionEnded } = setup([conversation([say("user", "x")])], (_m, url) =>
      Promise.resolve(url.pathname.endsWith("/messages") ? jsonResponse(401, {}) : undefined),
    );
    await open();

    await waitFor(() => {
      expect(sessionEnded).toHaveBeenCalled();
    });
  });

  it("refuses a history with an unknown tool status, showing nothing from it", async () => {
    const { open } = setup([
      conversation([
        say("user", "secret text"),
        say("assistant", "a", [{ name: "t", summary: "", status: "weird" }]),
      ]),
    ]);
    await open();

    expect(await screen.findByRole("alert")).toHaveTextContent("could not be opened");
    expect(document.body).not.toHaveTextContent("secret text");
  });
});

describe("timing", () => {
  it("loads once however often Open is clicked", async () => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    let reads = 0;
    const { user } = setup([conversation([say("user", "x")])], async (_m, url) => {
      if (url.pathname.endsWith("/messages")) {
        reads += 1;
        await gate;
      }
      return undefined;
    });
    const button = await screen.findByRole("button", { name: "Open Past chat" });
    await user.dblClick(button);

    expect(reads).toBe(1);
    release();
    expect(await screen.findByText("x", { selector: "p" })).toBeInTheDocument();
  });

  it("ignores a conversation that finishes loading after New conversation", async () => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const { open, user } = setup([conversation([say("user", "late arrival")])], async (_m, url) => {
      if (url.pathname.endsWith("/messages")) await gate;
      return undefined;
    });
    await open();
    await user.click(screen.getByRole("button", { name: "New conversation" }));
    release();
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(screen.queryByText("late arrival")).not.toBeInTheDocument();
  });
});
