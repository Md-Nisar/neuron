import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { fakeApi, thread } from "@/test/dataApi";
import { jsonResponse } from "@/test/sse";

import { FeedbackBar } from "./FeedbackBar";

const THREAD = thread(1, 2).thread_id;
const RUN = "5a7f2c10-1b2c-4d3e-8f90-a1b2c3d4e5f6";

function setup(options: { intercept?: (method: string) => Promise<Response | undefined> } = {}) {
  const api = fakeApi({ memories: [], threads: [thread(1, 2)] });
  const onSessionEnded = vi.fn();
  const doFetch: typeof fetch = async (input, init) =>
    (await options.intercept?.(init?.method ?? "GET")) ?? api.fetch(input, init);
  render(
    <FeedbackBar
      deps={{
        apiUrl: "http://127.0.0.1:8000",
        getAccessToken: () => "tok-1",
        onSessionEnded,
        fetch: doFetch,
      }}
      threadId={THREAD}
      runId={RUN}
    />,
  );
  const posts = () => api.calls.filter((call) => call.method === "POST");
  return { api, user: userEvent.setup(), posts, onSessionEnded };
}

const bodyOf = (init: HeadersInit | undefined) => init;

describe("FeedbackBar", () => {
  it("sends a thumbs up at once and shows the rating that is stored", async () => {
    const { user, posts } = setup();
    await user.click(screen.getByRole("button", { name: "Helpful" }));

    const done = await screen.findByText(/Your rating: Helpful\./);
    expect(done).toHaveFocus();
    const [post] = posts();
    expect(post?.url.pathname).toBe(`/v1/threads/${THREAD}/runs/${RUN}/feedback`);
    expect(bodyOf(post?.headers)).toMatchObject({
      Authorization: "Bearer tok-1",
      "Content-Type": "application/json",
    });
    expect(screen.queryByRole("button", { name: "Helpful" })).not.toBeInTheDocument();
  });

  it("asks for a fixed reason after a thumbs down, and sends it", async () => {
    const { user, api } = setup();
    await user.click(screen.getByRole("button", { name: "Not helpful" }));

    expect(screen.getByRole("group", { name: "What was wrong?" })).toHaveFocus();
    expect(api.calls.some((call) => call.method === "POST")).toBe(false);
    await user.click(screen.getByRole("button", { name: "Inaccurate" }));

    expect(
      await screen.findByText(/Your rating: Not helpful \(Inaccurate\)\./),
    ).toBeInTheDocument();
    expect(api.data.threads[0]?.ratings?.[RUN]).toEqual({ score: -1, reason: "inaccurate" });
  });

  it("can send a thumbs down with no reason", async () => {
    const { user, api } = setup();
    await user.click(screen.getByRole("button", { name: "Not helpful" }));
    await user.click(screen.getByRole("button", { name: "No reason" }));

    expect(await screen.findByText(/Your rating: Not helpful\./)).toBeInTheDocument();
    expect(api.data.threads[0]?.ratings?.[RUN]).toEqual({ score: -1, reason: null });
  });

  it("shows the rating the server kept when the run was already rated", async () => {
    const { user, api } = setup();
    const [first] = api.data.threads;
    if (first !== undefined) first.ratings = { [RUN]: { score: -1, reason: "unsafe" } };
    await user.click(screen.getByRole("button", { name: "Helpful" }));

    expect(await screen.findByText(/Your rating: Not helpful \(Unsafe\)\./)).toBeInTheDocument();
  });

  it("sends once however often the button is clicked", async () => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    let sent = 0;
    const { user } = setup({
      intercept: async (method) => {
        if (method === "POST") {
          sent += 1;
          await gate;
        }
        return undefined;
      },
    });
    const button = screen.getByRole("button", { name: "Helpful" });
    await user.dblClick(button);
    await user.click(button);

    expect(sent).toBe(1);
    release();
    expect(await screen.findByText(/Your rating/)).toBeInTheDocument();
  });

  it("ignores a second click that lands before the page has re-rendered", async () => {
    let sent = 0;
    setup({
      intercept: (method) => {
        if (method === "POST") sent += 1;
        return Promise.resolve(undefined);
      },
    });
    const button = screen.getByRole("button", { name: "Helpful" });
    await act(async () => {
      button.click();
      button.click(); // the same tick: the disabled attribute is not there yet
      await Promise.resolve();
    });

    expect(sent).toBe(1);
    expect(await screen.findByText(/Your rating/)).toBeInTheDocument();
  });

  it.each([
    [403, "You do not have permission to rate answers."],
    [404, "That conversation no longer exists."],
    [500, "Something went wrong on the server. Try again."],
  ])("shows a fixed message for a %i and lets the user try again", async (status, text) => {
    let fail = true;
    const { user } = setup({
      intercept: (method) =>
        Promise.resolve(
          method === "POST" && fail
            ? jsonResponse(status, { detail: "secret server detail" })
            : undefined,
        ),
    });
    await user.click(screen.getByRole("button", { name: "Helpful" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(text);
    expect(document.body).not.toHaveTextContent("secret server detail");
    fail = false;
    await user.click(screen.getByRole("button", { name: "Helpful" }));
    expect(await screen.findByText(/Your rating: Helpful\./)).toBeInTheDocument();
  });

  it("keeps the reasons after a failed thumbs down", async () => {
    const { user } = setup({
      intercept: (method) => Promise.resolve(method === "POST" ? jsonResponse(500, {}) : undefined),
    });
    await user.click(screen.getByRole("button", { name: "Not helpful" }));
    await user.click(screen.getByRole("button", { name: "Unsafe" }));

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Unsafe" })).toBeInTheDocument();
  });

  it("ends the session when the token is refused", async () => {
    const { user, onSessionEnded } = setup({
      intercept: (method) => Promise.resolve(method === "POST" ? jsonResponse(401, {}) : undefined),
    });
    await user.click(screen.getByRole("button", { name: "Helpful" }));

    await screen.findByRole("alert");
    expect(onSessionEnded).toHaveBeenCalled();
  });
});
