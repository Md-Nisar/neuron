import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SignedInView } from "@/SignedInView";
import { fakeApi, thread } from "@/test/dataApi";
import { controlledStream, frame, sseResponse, streamOf } from "@/test/sse";

const NEW_THREAD = thread(7, 0).thread_id;
const RUN = "5a7f2c10-1b2c-4d3e-8f90-a1b2c3d4e5f6";

function reply(answer: string): Response {
  return sseResponse(
    streamOf([
      frame("run_started", { request_id: "r1", thread_id: NEW_THREAD, run_id: RUN }),
      frame("token", { text: answer }),
      frame("final", {
        status: "completed",
        request_id: "r1",
        thread_id: NEW_THREAD,
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

function setup() {
  const api = fakeApi({ memories: [], threads: [] });
  const fetchMock = vi.fn<typeof fetch>((input, init) => {
    const url = new URL(input instanceof URL ? input.href : (input as string));
    if (url.pathname !== "/v1/agent/stream") return api.fetch(input, init);
    // The server files the new conversation under the first message's title.
    api.data.threads = [
      { ...thread(7, 2), title: "hello there", thread_id: NEW_THREAD },
      ...api.data.threads,
    ];
    return Promise.resolve(reply("general kenobi"));
  });
  vi.stubGlobal("fetch", fetchMock);
  render(
    <SignedInView
      auth={{
        displayName: "alice",
        getAccessToken: () => "tok-1",
        sessionEnded: vi.fn(),
        signOut: vi.fn(),
      }}
      apiUrl="http://127.0.0.1:8000"
      maxChars={12_000}
    />,
  );
  return { api, user: userEvent.setup() };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("rating an answer", () => {
  it("offers a rating on a finished answer and files it under that run", async () => {
    const { user, api } = setup();
    await user.click(screen.getByRole("textbox", { name: "Message" }));
    await user.paste("hello there");
    await user.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByText("general kenobi");

    await user.click(await screen.findByRole("button", { name: "Helpful" }));

    expect(await screen.findByText(/Your rating: Helpful\./)).toBeInTheDocument();
    const post = api.calls.find((call) => call.method === "POST");
    expect(post?.url.pathname).toBe(`/v1/threads/${NEW_THREAD}/runs/${RUN}/feedback`);
  });

  it("offers none while the answer is still arriving", async () => {
    const hold = controlledStream();
    const api = fakeApi({ memories: [], threads: [] });
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>((input, init) => {
        const url = new URL(input instanceof URL ? input.href : (input as string));
        return url.pathname === "/v1/agent/stream"
          ? Promise.resolve(sseResponse(hold.stream))
          : api.fetch(input, init);
      }),
    );
    render(
      <SignedInView
        auth={{
          displayName: "alice",
          getAccessToken: () => "tok-1",
          sessionEnded: vi.fn(),
          signOut: vi.fn(),
        }}
        apiUrl="http://127.0.0.1:8000"
        maxChars={12_000}
      />,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("textbox", { name: "Message" }));
    await user.paste("hello");
    await user.click(screen.getByRole("button", { name: "Send" }));
    hold.push(frame("run_started", { request_id: "r", thread_id: NEW_THREAD, run_id: RUN }));
    hold.push(frame("token", { text: "partial answer" }));
    await screen.findByText("partial answer");

    expect(screen.queryByRole("button", { name: "Helpful" })).not.toBeInTheDocument();
  });
});

describe("SignedInView", () => {
  it("lists a new conversation as soon as its first reply finishes", async () => {
    const { user } = setup();
    expect(await screen.findByText("No conversations yet.")).toBeInTheDocument();

    await user.click(screen.getByRole("textbox", { name: "Message" }));
    await user.paste("hello there");
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText("general kenobi")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Rename hello there" })).toBeInTheDocument();
    expect(screen.queryByText("No conversations yet.")).not.toBeInTheDocument();
  });

  it("clears the open chat when its conversation is deleted from the list", async () => {
    const { user, api } = setup();
    await user.click(screen.getByRole("textbox", { name: "Message" }));
    await user.paste("hello there");
    await user.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByText("general kenobi");
    await user.click(await screen.findByRole("button", { name: "Delete hello there" }));
    await user.click(screen.getByRole("button", { name: "Confirm delete" }));

    await waitFor(() => {
      expect(screen.queryByText("general kenobi")).not.toBeInTheDocument();
    });
    expect(api.data.threads).toHaveLength(0);
  });

  it("keeps the open chat when another conversation is deleted", async () => {
    const { user, api } = setup();
    api.data.threads = [{ ...thread(1, 2), title: "other" }];
    await user.click(screen.getByRole("textbox", { name: "Message" }));
    await user.paste("hello there");
    await user.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByText("general kenobi");
    await user.click(await screen.findByRole("button", { name: "Delete other" }));
    await user.click(screen.getByRole("button", { name: "Confirm delete" }));

    await waitFor(() => {
      expect(screen.queryByText("other")).not.toBeInTheDocument();
    });
    expect(screen.getByText("general kenobi")).toBeInTheDocument();
  });
});
