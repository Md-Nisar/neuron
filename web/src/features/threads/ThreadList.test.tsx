import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { fakeApi, thread, type FakeThread } from "@/test/dataApi";
import { jsonResponse } from "@/test/sse";

import { ThreadList } from "./ThreadList";

const withTitle = (n: number, title: string | null): FakeThread => ({ ...thread(n, 2), title });
const ZERO_WIDTH = String.fromCodePoint(0x200b);
const RLO = String.fromCodePoint(0x202e);

function setup(
  threads: FakeThread[],
  options: {
    token?: string | null;
    fetch?: typeof fetch;
    refresh?: number;
    active?: string;
    openDisabled?: boolean;
    /** Answers a request itself (or delays it); resolving to undefined lets the fake serve it. */
    intercept?: (method: string, url: URL) => Promise<Response | undefined>;
  } = {},
) {
  const api = fakeApi({ memories: [], threads });
  const onSessionEnded = vi.fn();
  const onDeleted = vi.fn();
  const onOpen = vi.fn();
  const user = userEvent.setup();
  const gated: typeof fetch = async (input, init) =>
    (await options.intercept?.(
      init?.method ?? "GET",
      new URL(input instanceof URL ? input.href : (input as string)),
    )) ?? api.fetch(input, init);
  const doFetch = options.fetch ?? gated;
  const ui = (refresh: number) => (
    <ThreadList
      deps={{
        apiUrl: "http://127.0.0.1:8000",
        getAccessToken: () => (options.token === undefined ? "tok-1" : options.token),
        onSessionEnded,
        fetch: doFetch,
      }}
      refresh={refresh}
      onDeleted={onDeleted}
      onOpen={onOpen}
      activeThreadId={options.active ?? null}
      openDisabled={options.openDisabled ?? false}
    />
  );
  const view = render(ui(options.refresh ?? 0));
  return {
    api,
    user,
    onSessionEnded,
    onDeleted,
    onOpen,
    rerender: (n: number) => {
      view.rerender(ui(n));
    },
  };
}

describe("ThreadList", () => {
  it("lists conversations with their titles, and a fallback for a missing title", async () => {
    setup([withTitle(1, "Trip to Lisbon"), withTitle(2, null)]);

    expect(await screen.findByText("Trip to Lisbon")).toBeInTheDocument();
    expect(screen.getByText("Untitled conversation")).toBeInTheDocument();
    expect(screen.getAllByText(/2 messages/)).toHaveLength(2);
  });

  it("shows a title as text only: markup stays inert and invisible characters are marked", async () => {
    const payload = '<img src=x onerror="alert(1)"><script>alert(2)</script>';
    const { api } = setup([
      withTitle(1, payload),
      withTitle(2, `hidden${ZERO_WIDTH}word`),
      withTitle(3, `gnp${RLO}.exe`),
    ]);

    expect(await screen.findByText(payload)).toBeInTheDocument();
    expect(document.querySelector("img, script")).toBeNull();
    expect(screen.getByText("hidden[U+200B]word")).toBeInTheDocument();
    expect(screen.getByText("gnp[U+202E].exe")).toBeInTheDocument();
    expect(api.fetch).toHaveBeenCalledTimes(1);
  });

  it("says so when there are none, and when the list cannot be loaded", async () => {
    setup([]);
    expect(await screen.findByText("No conversations yet.")).toBeInTheDocument();
  });

  it("shows a fixed message when loading fails, never the server's text", async () => {
    const failing = vi.fn<typeof fetch>(() =>
      Promise.resolve(jsonResponse(500, { detail: "secret internal detail" })),
    );
    setup([], { fetch: failing });

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Something went wrong on the server. Try again.",
    );
    expect(document.body).not.toHaveTextContent("secret internal detail");
    expect(screen.queryByText("No conversations yet.")).not.toBeInTheDocument();
  });

  it("ends the session when the token is refused or missing", async () => {
    const refused = vi.fn<typeof fetch>(() => Promise.resolve(jsonResponse(401, {})));
    const first = setup([], { fetch: refused });
    await waitFor(() => {
      expect(first.onSessionEnded).toHaveBeenCalled();
    });
    const second = setup([], { token: null });
    await waitFor(() => {
      expect(second.onSessionEnded).toHaveBeenCalled();
    });
  });

  it("loads further pages on request, without duplicates", async () => {
    const all = Array.from({ length: 35 }, (_, i) => withTitle(i + 1, `chat ${String(i + 1)}`));
    const { user, api } = setup(all);
    await screen.findByText("chat 1");
    expect(screen.getAllByRole("listitem")).toHaveLength(30);

    await user.click(screen.getByRole("button", { name: "Load more" }));

    expect(await screen.findByText("chat 35")).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(35);
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
    expect(api.calls.map((call) => call.url.search)).toEqual([
      "?limit=30&offset=0",
      "?limit=30&offset=30",
    ]);
  });

  it("ignores a page that arrives after the list was reloaded", async () => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const all = Array.from({ length: 35 }, (_, i) => withTitle(i + 1, `chat ${String(i + 1)}`));
    const { user, api, rerender } = setup(all, {
      intercept: async (_method, url) => {
        if (url.searchParams.get("offset") !== "30") return undefined;
        await gate;
        return jsonResponse(200, {
          threads: [
            {
              thread_id: "stale-id",
              title: "stale page",
              updated_at: "2026-10-02T10:00:00Z",
              message_count: 1,
            },
          ],
          total: 99,
        });
      },
    });
    await screen.findByText("chat 1");
    await user.click(screen.getByRole("button", { name: "Load more" }));
    api.data.threads = [withTitle(1, "after reload")];
    rerender(1);
    await screen.findByText("after reload");
    release();
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(screen.queryByText("stale page")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
  });

  it("reloads the first page when told a reply finished", async () => {
    const { api, rerender } = setup([withTitle(1, "first")]);
    await screen.findByText("first");
    api.data.threads = [withTitle(2, "second"), ...api.data.threads];

    rerender(1);

    expect(await screen.findByText("second")).toBeInTheDocument();
    expect(screen.getByText("first")).toBeInTheDocument();
  });
});

describe("opening", () => {
  it("opens the conversation that was clicked, and marks the current one", async () => {
    const { user, onOpen } = setup([withTitle(1, "first"), withTitle(2, "second")], {
      active: thread(2, 2).thread_id,
    });
    await screen.findByText("first");

    await user.click(screen.getByRole("button", { name: "Open first" }));

    expect(onOpen).toHaveBeenCalledExactlyOnceWith(thread(1, 2).thread_id);
    expect(screen.getByRole("button", { name: "Open second" })).toHaveAttribute(
      "aria-current",
      "true",
    );
    expect(screen.getByRole("button", { name: "Open first" })).not.toHaveAttribute("aria-current");
  });

  it("cannot be used while a reply is streaming or another conversation loads", async () => {
    const { user, onOpen } = setup([withTitle(1, "first")], { openDisabled: true });
    await screen.findByText("first");

    await user.click(screen.getByRole("button", { name: "Open first" }));

    expect(screen.getByRole("button", { name: "Open first" })).toBeDisabled();
    expect(onOpen).not.toHaveBeenCalled();
  });
});

describe("renaming", () => {
  async function startRename(
    title: string,
    intercept?: (method: string) => Promise<Response | undefined>,
  ) {
    const ctx = setup([withTitle(1, title)], intercept === undefined ? {} : { intercept });
    await screen.findByText(title);
    await ctx.user.click(screen.getByRole("button", { name: `Rename ${title}` }));
    return { ...ctx, box: () => screen.getByRole("textbox", { name: "Conversation title" }) };
  }

  it("saves with Enter, shows the title the server stored, and returns focus", async () => {
    const { user, api } = await startRename("old");
    const box = screen.getByRole("textbox", { name: "Conversation title" });
    await user.clear(box);
    await user.type(box, "  new   name {Enter}");

    expect(await screen.findByText("new name")).toBeInTheDocument();
    const patch = api.calls.find((call) => call.method === "PATCH");
    expect(patch?.url.pathname).toBe(`/v1/threads/${thread(1, 2).thread_id}`);
    expect(patch?.headers).toMatchObject({
      Authorization: "Bearer tok-1",
      "Content-Type": "application/json",
    });
    expect(screen.getByRole("button", { name: "Rename new name" })).toHaveFocus();
  });

  it("cancels with Escape or Cancel without a request", async () => {
    const { user, api } = await startRename("old");
    await user.type(screen.getByRole("textbox", { name: "Conversation title" }), "x{Escape}");

    expect(screen.getByRole("button", { name: "Rename old" })).toHaveFocus();
    await user.click(screen.getByRole("button", { name: "Rename old" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(api.calls.some((call) => call.method === "PATCH")).toBe(false);
    expect(screen.getByText("old")).toBeInTheDocument();
  });

  it.each([
    ["empty", ""],
    ["too long", "z".repeat(60)],
  ])("refuses a %s title before sending", async (_name, typed) => {
    const { user, api } = await startRename("old");
    const box = screen.getByRole("textbox", { name: "Conversation title" });
    await user.clear(box);
    if (typed !== "") await user.click(box);
    if (typed !== "") await user.paste(typed + typed);
    await user.keyboard("{Enter}");

    expect(await screen.findByRole("alert")).toHaveTextContent("Use 1 to 80 characters.");
    expect(api.calls.some((call) => call.method === "PATCH")).toBe(false);
    expect(box).toHaveAccessibleDescription("Use 1 to 80 characters.");
  });

  it("shows a fixed message when the server refuses the title, and keeps the form", async () => {
    const { user, box } = await startRename("old", (method) =>
      Promise.resolve(
        method === "PATCH" ? jsonResponse(422, { detail: "validation_error" }) : undefined,
      ),
    );
    await user.clear(box());
    await user.type(box(), "whatever{Enter}");

    expect(await screen.findByRole("alert")).toHaveTextContent("That title can't be used.");
    expect(box()).toHaveValue("whatever");
  });

  it("sends once however often Enter is pressed while the request is in flight", async () => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    let patches = 0;
    const { user } = setup([withTitle(1, "old")], {
      intercept: async (method) => {
        if (method === "PATCH") {
          patches += 1;
          await gate;
        }
        return undefined;
      },
    });
    await screen.findByText("old");
    await user.click(screen.getByRole("button", { name: "Rename old" }));
    const box = screen.getByRole("textbox", { name: "Conversation title" });
    await user.clear(box);
    await user.type(box, "renamed{Enter}{Enter}{Enter}");

    expect(patches).toBe(1);
    release();
    expect(await screen.findByText("renamed")).toBeInTheDocument();
  });
});

describe("deleting", () => {
  it("asks first, deletes on confirm, moves focus to the heading and tells the page", async () => {
    const { user, api, onDeleted } = setup([withTitle(1, "doomed"), withTitle(2, "kept")]);
    await screen.findByText("doomed");

    await user.click(screen.getByRole("button", { name: "Delete doomed" }));
    expect(api.calls.some((call) => call.method === "DELETE")).toBe(false);
    await user.click(screen.getByRole("button", { name: "Confirm delete" }));

    await waitFor(() => {
      expect(screen.queryByText("doomed")).not.toBeInTheDocument();
    });
    expect(screen.getByText("kept")).toBeInTheDocument();
    expect(api.calls.filter((call) => call.method === "DELETE")).toHaveLength(1);
    expect(screen.getByRole("heading", { name: "Conversations" })).toHaveFocus();
    expect(onDeleted).toHaveBeenCalledExactlyOnceWith(thread(1, 2).thread_id);
  });

  it("changes nothing when cancelled, and returns focus to the Delete button", async () => {
    const { user, api, onDeleted } = setup([withTitle(1, "kept")]);
    await screen.findByText("kept");
    await user.click(screen.getByRole("button", { name: "Delete kept" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.getByRole("button", { name: "Delete kept" })).toHaveFocus();
    expect(api.calls.some((call) => call.method === "DELETE")).toBe(false);
    expect(onDeleted).not.toHaveBeenCalled();
  });

  it("drops a conversation that was already gone and says so", async () => {
    const { user, api, onDeleted } = setup([withTitle(1, "ghost")]);
    await screen.findByText("ghost");
    api.data.threads = []; // deleted elsewhere
    await user.click(screen.getByRole("button", { name: "Delete ghost" }));
    await user.click(screen.getByRole("button", { name: "Confirm delete" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "That conversation no longer exists.",
    );
    expect(within(screen.getByRole("list")).queryByText("ghost")).not.toBeInTheDocument();
    expect(onDeleted).toHaveBeenCalledOnce();
  });

  it("keeps the conversation and shows a fixed message when the delete fails", async () => {
    const { user, onDeleted } = setup([withTitle(1, "stays")], {
      intercept: (method) =>
        Promise.resolve(
          method === "DELETE" ? jsonResponse(500, { detail: "database exploded" }) : undefined,
        ),
    });
    await screen.findByText("stays");
    await user.click(screen.getByRole("button", { name: "Delete stays" }));
    await user.click(screen.getByRole("button", { name: "Confirm delete" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Something went wrong on the server.",
    );
    expect(document.body).not.toHaveTextContent("database exploded");
    expect(screen.getByText("stays")).toBeInTheDocument();
    expect(onDeleted).not.toHaveBeenCalled();
  });
});
