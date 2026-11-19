import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { accessibilityViolations } from "@/test/axe";
import { jsonResponse } from "@/test/sse";

import { KnowledgeScreen } from "./KnowledgeScreen";

const kb = (n: number, name: string, processing = "hosted", access = "owner") => ({
  kb_id: `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`,
  name,
  processing,
  language: "simple",
  created_at: "2026-11-01T10:00:00Z",
  access,
  document_count: null as number | null,
});

/** A fetch that answers `GET` with the bases and any change with `reply`. */
function setup(bases: unknown[], reply?: { status: number; body: unknown }) {
  const fetch = vi.fn<typeof globalThis.fetch>((input, init) =>
    Promise.resolve(
      init?.method !== "GET"
        ? jsonResponse(reply?.status ?? 201, reply?.body)
        : (input instanceof URL ? input.pathname : "").endsWith("/bases")
          ? jsonResponse(200, { bases })
          : (input instanceof URL ? input.pathname : "").endsWith("/grants")
            ? jsonResponse(200, { grants: [] })
            : jsonResponse(200, { documents: [], total: 0 }),
    ),
  );
  const user = userEvent.setup();
  const view = render(
    <KnowledgeScreen
      deps={{
        apiUrl: "http://127.0.0.1:8000",
        getAccessToken: () => "tok-1",
        onSessionEnded: vi.fn(),
        fetch,
      }}
    />,
  );
  return { fetch, user, view };
}

describe("knowledge bases", () => {
  it("lists them as text, with where each is processed and how many documents", async () => {
    const hostile = '<img src=x onerror="alert(1)">';
    const { view } = setup([
      { ...kb(1, "Policies"), document_count: 3 },
      kb(2, hostile, "self_hosted"),
    ]);

    expect(await screen.findByRole("button", { name: "Policies" })).toBeInTheDocument();
    expect(screen.getByText(hostile)).toBeInTheDocument();
    expect(view.container.querySelector("ul img")).toBeNull();
    expect(screen.getByText("Hosted", { selector: "[data-slot=badge]" })).toBeInTheDocument();
    expect(
      screen.getByText("Self-hosted only", { selector: "[data-slot=badge]" }),
    ).toBeInTheDocument();
    expect(screen.getByText("3 documents")).toBeInTheDocument();
    expect(screen.getByText("2 knowledge bases")).toBeInTheDocument();
  });

  it("says where text is processed, then creates one with the chosen processing", async () => {
    const { fetch, user } = setup([], { status: 201, body: kb(3, "Contracts", "self_hosted") });
    await screen.findByText("No knowledge bases yet");
    await user.click(screen.getByRole("button", { name: "New knowledge base" }));
    const dialog = screen.getByRole("dialog", { name: "New knowledge base" });
    expect(within(dialog).getByRole("radio", { name: /^Hosted/ })).toBeChecked();
    expect(within(dialog).getByText(/sent to the configured embedding provider/)).toBeVisible();

    await user.type(within(dialog).getByLabelText("Name"), "  Contracts ");
    await user.click(within(dialog).getByRole("radio", { name: /^Self-hosted only/ }));
    // The language of its documents (RAG-09.08): exact words unless the user picks one.
    const language = within(dialog).getByLabelText("Language of its documents");
    expect(language).toHaveValue("simple");
    await user.selectOptions(language, "German");
    await user.click(within(dialog).getByRole("button", { name: "Create" }));

    // The new base opens, ready for its first upload, with focus on its name.
    const heading = await screen.findByRole("heading", { name: "Contracts", level: 1 });
    await waitFor(() => {
      expect(heading).toHaveFocus();
    });
    expect(screen.queryByRole("dialog")).toBeNull();
    const [, init] = fetch.mock.calls[1] ?? [];
    expect(JSON.parse(init?.body as string)).toEqual({
      name: "Contracts",
      processing: "self_hosted",
      language: "german",
    });
    expect(screen.getByRole("heading", { name: /Documents in Contracts/ })).toBeInTheDocument();
    expect(screen.getByText("Drop files here, or choose files")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "All knowledge bases" }));
    expect(await screen.findByRole("button", { name: "Contracts" })).toBeInTheDocument();
    expect(screen.getByText("0 documents")).toBeInTheDocument();
  });

  it("refuses an empty name without calling the API", async () => {
    const { fetch, user } = setup([]);
    await screen.findByText("No knowledge bases yet");
    await user.click(screen.getByRole("button", { name: "Create a knowledge base" }));

    await user.click(screen.getByRole("button", { name: "Create" }));

    expect(screen.getByRole("alert")).toHaveTextContent("Use 1 to 80 characters.");
    expect(screen.getByLabelText("Name")).toHaveAttribute("aria-invalid", "true");
    expect(fetch).toHaveBeenCalledOnce();
  });

  it("says when the limit is reached, in its own words, and keeps the dialog open", async () => {
    const { user } = setup([], { status: 409, body: { detail: "knowledge_base_limit_reached" } });
    await screen.findByText("No knowledge bases yet");
    await user.click(screen.getByRole("button", { name: "New knowledge base" }));

    await user.type(screen.getByLabelText("Name"), "One more{Enter}");

    const dialog = screen.getByRole("dialog", { name: "New knowledge base" });
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "You have reached the limit of knowledge bases. Delete one to create another.",
    );
    expect(screen.getByLabelText("Name")).toHaveValue("One more");
  });

  it("says when knowledge is turned off", async () => {
    const fetch = vi.fn<typeof globalThis.fetch>(() =>
      Promise.resolve(jsonResponse(404, { detail: "knowledge_disabled" })),
    );
    render(
      <KnowledgeScreen
        deps={{
          apiUrl: "http://127.0.0.1:8000",
          getAccessToken: () => "t",
          onSessionEnded: vi.fn(),
          fetch,
        }}
      />,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Knowledge bases are turned off for this service.",
    );
  });

  it("renames one from its menu, and the list shows the new name", async () => {
    const { fetch, user } = setup([{ ...kb(1, "Policies"), document_count: 4 }], {
      status: 200,
      body: kb(1, "Rules"),
    });
    await user.click(await screen.findByRole("button", { name: "Actions for Policies" }));
    await user.click(screen.getByRole("menuitem", { name: "Rename" }));
    const input = screen.getByRole("textbox", { name: "Name" });
    expect(input).toHaveValue("Policies");

    await user.clear(input);
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Use 1 to 80 characters.");
    await user.type(input, "Rules{Enter}");

    expect(await screen.findByRole("button", { name: "Rules" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
    // The rename keeps the count the list had.
    expect(screen.getByText("4 documents")).toBeInTheDocument();
    const [url, init] = fetch.mock.calls[1] ?? [];
    expect(init?.method).toBe("PATCH");
    expect(url instanceof URL ? url.pathname : "").toBe(`/v1/knowledge/bases/${kb(1, "").kb_id}`);
    expect(JSON.parse(init?.body as string)).toEqual({ name: "Rules" });
  });

  it("deletes one only after confirming, then puts focus on the page heading", async () => {
    const { fetch, user } = setup([kb(1, "Policies"), kb(2, "Contracts")], {
      status: 202,
      body: null,
    });
    await user.click(await screen.findByRole("button", { name: "Actions for Policies" }));
    await user.click(screen.getByRole("menuitem", { name: "Delete" }));
    const confirm = screen.getByRole("alertdialog", { name: "Delete Policies?" });
    // Cancel is the safe default.
    expect(within(confirm).getByRole("button", { name: "Cancel" })).toHaveFocus();
    await user.click(within(confirm).getByRole("button", { name: "Cancel" }));
    expect(fetch).toHaveBeenCalledOnce();

    await user.click(screen.getByRole("button", { name: "Actions for Policies" }));
    await user.click(screen.getByRole("menuitem", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "Delete knowledge base" }));

    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Policies" })).not.toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "Contracts" })).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Knowledge", level: 1 })).toHaveFocus();
    });
    expect(fetch.mock.calls[1]?.[1]?.method).toBe("DELETE");
  });

  it("deletes the open one from its own page and goes back to the list", async () => {
    const { user } = setup([kb(1, "Policies")], { status: 202, body: null });
    await user.click(await screen.findByRole("button", { name: "Policies" }));
    await user.click(screen.getByRole("button", { name: "Actions for Policies" }));
    await user.click(screen.getByRole("menuitem", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "Delete knowledge base" }));

    expect(await screen.findByText("No knowledge bases yet")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Knowledge", level: 1 })).toHaveFocus();
    });
  });

  it("drops a base that another tab already deleted", async () => {
    const { user } = setup([kb(1, "Policies")], {
      status: 404,
      body: { detail: "knowledge_base_not_found" },
    });
    await user.click(await screen.findByRole("button", { name: "Actions for Policies" }));
    await user.click(screen.getByRole("menuitem", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "Delete knowledge base" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "That knowledge base no longer exists.",
    );
    expect(screen.queryByRole("button", { name: "Policies" })).not.toBeInTheDocument();
  });

  it("finds, filters and sorts them, and clears a search that matches none", async () => {
    const { user } = setup([
      { ...kb(1, "beta"), created_at: "2026-11-01T10:00:00Z" },
      { ...kb(2, "Alpha"), created_at: "2026-11-03T10:00:00Z" },
      { ...kb(3, "Gamma", "hosted", "read"), created_at: "2026-11-02T10:00:00Z" },
    ]);
    const names = () =>
      within(screen.getByRole("list", { name: "Your knowledge bases" }))
        .getAllByRole("listitem")
        .map((item) => item.querySelector("button:not([aria-label])")?.textContent);
    await screen.findByRole("button", { name: "Alpha" });

    expect(names()).toEqual(["Alpha", "Gamma", "beta"]);
    await user.selectOptions(screen.getByLabelText("Sort by"), "Name");
    expect(names()).toEqual(["Alpha", "beta", "Gamma"]);
    await user.selectOptions(screen.getByLabelText("Sort by"), "Oldest first");
    expect(names()).toEqual(["beta", "Gamma", "Alpha"]);

    await user.selectOptions(screen.getByLabelText("Show"), "Shared with you");
    expect(names()).toEqual(["Gamma"]);
    await user.selectOptions(screen.getByLabelText("Show"), "Created by you");
    expect(names()).toEqual(["beta", "Alpha"]);
    expect(screen.getByText("2 of 3 knowledge bases")).toBeInTheDocument();

    await user.type(screen.getByLabelText("Search knowledge bases"), "zzz");
    expect(screen.getByText("No knowledge bases match")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Clear search and filters" }));
    expect(names()).toHaveLength(3);
    expect(screen.getByLabelText("Search knowledge bases")).toHaveValue("");
  });

  it("switches between a grid and a list, and remembers the choice", async () => {
    localStorage.removeItem("neuron.knowledge.layout");
    const { user, view } = setup([kb(1, "Policies")]);
    await screen.findByRole("button", { name: "Policies" });
    expect(screen.getByRole("button", { name: "Grid view" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    await user.click(screen.getByRole("button", { name: "List view" }));

    expect(screen.getByRole("button", { name: "List view" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(localStorage.getItem("neuron.knowledge.layout")).toBe("list");
    view.unmount();
    setup([kb(1, "Policies")]);
    await screen.findByRole("button", { name: "Policies" });
    expect(screen.getByRole("button", { name: "List view" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    localStorage.removeItem("neuron.knowledge.layout");
  });

  it("has no accessibility violations, in the grid, the list, and on a base's page", async () => {
    const { user, view } = setup([kb(1, "Policies"), kb(2, "Shared", "hosted", "read")]);
    await screen.findByRole("button", { name: "Policies" });
    expect(await accessibilityViolations(view.container)).toEqual([]);

    await user.click(screen.getByRole("button", { name: "List view" }));
    expect(await accessibilityViolations(view.container)).toEqual([]);
    localStorage.removeItem("neuron.knowledge.layout");

    await user.click(screen.getByRole("button", { name: "Policies" }));
    await screen.findByRole("heading", { name: "Policies", level: 1 });
    expect(await accessibilityViolations(view.container)).toEqual([]);
  });
});

describe("bases shared with the user (RAG-09.03)", () => {
  it.each([
    ["owner", "", true, true, true, true],
    ["admin", "Shared with you · Manage", true, false, true, true],
    ["write", "Shared with you · Read and edit", false, false, false, true],
    ["read", "Shared with you · Read", false, false, false, false],
  ])(
    "with %s access, offers only what the server allows",
    async (access, badge, rename, remove, sharing, upload) => {
      const { user } = setup([kb(1, "Policies", "hosted", access)]);
      await user.click(await screen.findByRole("button", { name: "Policies" }));
      await screen.findByRole("heading", { name: /Documents in Policies/ });

      if (badge !== "") expect(screen.getByText(badge)).toBeInTheDocument();
      else expect(screen.queryByText(/Shared with you/)).toBeNull();
      expect(screen.queryByRole("tab", { name: "Sharing" }) !== null).toBe(sharing);
      expect(screen.queryByRole("button", { name: "Upload files" }) !== null).toBe(upload);
      expect(screen.queryByText("Drop files here, or choose files") !== null).toBe(upload);

      await user.click(screen.getByRole("button", { name: "Actions for Policies" }));
      expect(screen.queryByRole("menuitem", { name: "Rename" }) !== null).toBe(rename);
      expect(screen.queryByRole("menuitem", { name: "Delete" }) !== null).toBe(remove);
    },
  );

  it("shows who it is shared with on the Sharing tab", async () => {
    const { user } = setup([kb(1, "Policies")]);
    await user.click(await screen.findByRole("button", { name: "Policies" }));
    await user.click(screen.getByRole("tab", { name: "Sharing" }));

    expect(await screen.findByRole("heading", { name: "Sharing Policies" })).toBeInTheDocument();
  });
});

describe("loading the list after a passing refusal (UX-01)", () => {
  /** A fetch whose `GET /bases` calls get `replies` in order, then the last one again. */
  function loading(replies: Response[]) {
    let call = 0;
    const fetch = vi.fn<typeof globalThis.fetch>(() =>
      Promise.resolve((replies[Math.min(call++, replies.length - 1)] as Response).clone()),
    );
    render(
      <KnowledgeScreen
        deps={{
          apiUrl: "http://127.0.0.1:8000",
          getAccessToken: () => "tok-1",
          onSessionEnded: vi.fn(),
          fetch,
        }}
      />,
    );
    return fetch;
  }

  it("waits for Retry-After, tries again and shows the list", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      loading([
        jsonResponse(429, { detail: "rate_limited" }, { "Retry-After": "2" }),
        jsonResponse(200, { bases: [kb(1, "Policies")] }),
      ]);
      expect(await screen.findByText(/Too many requests/)).toBeInTheDocument();

      await act(() => vi.advanceTimersByTimeAsync(2000));

      expect(await screen.findByText("Policies")).toBeInTheDocument();
      expect(screen.queryByText(/Too many requests/)).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("gives up after three tries and keeps the message", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const fetch = loading([jsonResponse(503, {})]);
      for (let step = 0; step < 6; step++) await act(() => vi.advanceTimersByTimeAsync(5000));
      expect(fetch).toHaveBeenCalledTimes(4);
      expect(screen.getByText(/unavailable right now/)).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("does not try again when it is not permitted", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const fetch = loading([jsonResponse(403, {}), jsonResponse(200, { bases: [] })]);
      await act(() => vi.advanceTimersByTimeAsync(60_000));
      expect(fetch).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });
});
