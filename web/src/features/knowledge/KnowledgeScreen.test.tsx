import { act, render, screen, waitFor } from "@testing-library/react";
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
  it("lists them as text, with where each is processed", async () => {
    const hostile = '<img src=x onerror="alert(1)">';
    const { view } = setup([kb(1, "Policies"), kb(2, hostile, "self_hosted")]);

    expect(await screen.findByText("Policies")).toBeInTheDocument();
    expect(screen.getByText(hostile)).toBeInTheDocument();
    expect(view.container.querySelector("ul img")).toBeNull();
    expect(screen.getByText("Hosted", { selector: "[data-slot=badge]" })).toBeInTheDocument();
    expect(
      screen.getByText("Self-hosted only", { selector: "[data-slot=badge]" }),
    ).toBeInTheDocument();
  });

  it("says where text is processed, then creates one with the chosen processing", async () => {
    const { fetch, user } = setup([], { status: 201, body: kb(3, "Contracts", "self_hosted") });
    await screen.findByText("No knowledge bases yet.");
    expect(screen.getByRole("radio", { name: /^Hosted\./ })).toBeChecked();
    expect(screen.getByText(/sent to the configured embedding provider/)).toBeInTheDocument();

    await user.type(screen.getByLabelText("New knowledge base"), "  Contracts ");
    await user.click(screen.getByRole("radio", { name: /^Self-hosted only\./ }));
    // The language of its documents (RAG-09.08): exact words unless the user picks one.
    const language = screen.getByLabelText("Language of its documents");
    expect(language).toHaveValue("simple");
    await user.selectOptions(language, "German");
    await user.click(screen.getByRole("button", { name: "Create" }));

    expect(await screen.findByText("Contracts")).toBeInTheDocument();
    const [, init] = fetch.mock.calls[1] ?? [];
    expect(JSON.parse(init?.body as string)).toEqual({
      name: "Contracts",
      processing: "self_hosted",
      language: "german",
    });
    expect(screen.getByLabelText("New knowledge base")).toHaveValue("");
    // The new base opens, ready for its first upload.
    expect(screen.getByRole("button", { name: "Contracts" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("heading", { name: "Documents in Contracts" })).toBeInTheDocument();
  });

  it("refuses an empty name without calling the API", async () => {
    const { fetch, user } = setup([]);
    await screen.findByText("No knowledge bases yet.");

    await user.click(screen.getByRole("button", { name: "Create" }));

    expect(screen.getByRole("alert")).toHaveTextContent("Use 1 to 80 characters.");
    expect(fetch).toHaveBeenCalledOnce();
  });

  it("says when the limit is reached, in its own words", async () => {
    const { user } = setup([], { status: 409, body: { detail: "knowledge_base_limit_reached" } });
    await screen.findByText("No knowledge bases yet.");

    await user.type(screen.getByLabelText("New knowledge base"), "One more");
    await user.click(screen.getByRole("button", { name: "Create" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "You have reached the limit of knowledge bases. Delete one to create another.",
    );
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

  it("renames one and returns focus to its rename button", async () => {
    const { fetch, user } = setup([kb(1, "Policies")], { status: 200, body: kb(1, "Rules") });
    await user.click(await screen.findByRole("button", { name: "Rename Policies" }));
    const input = screen.getByRole("textbox", { name: "New name for Policies" });

    await user.clear(input);
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Use 1 to 80 characters.");
    await user.type(input, "Rules{Enter}");

    expect(await screen.findByRole("button", { name: "Rename Rules" })).toHaveFocus();
    const [url, init] = fetch.mock.calls[1] ?? [];
    expect(init?.method).toBe("PATCH");
    expect(url instanceof URL ? url.pathname : "").toBe(`/v1/knowledge/bases/${kb(1, "").kb_id}`);
    expect(JSON.parse(init?.body as string)).toEqual({ name: "Rules" });
  });

  it("deletes one only after confirming, then keeps focus in the section", async () => {
    const { fetch, user } = setup([kb(1, "Policies"), kb(2, "Contracts")], {
      status: 202,
      body: null,
    });
    await user.click(await screen.findByRole("button", { name: "Delete Policies" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByRole("button", { name: "Delete Policies" })).toHaveFocus();
    expect(fetch).toHaveBeenCalledOnce();

    await user.click(screen.getByRole("button", { name: "Delete Policies" }));
    await user.click(screen.getByRole("button", { name: "Confirm delete" }));

    await waitFor(() => {
      expect(screen.queryByText("Policies")).not.toBeInTheDocument();
    });
    expect(screen.getByText("Contracts")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Knowledge bases" })).toHaveFocus();
    expect(fetch.mock.calls[1]?.[1]?.method).toBe("DELETE");
  });

  it("drops a base that another tab already deleted", async () => {
    const { user } = setup([kb(1, "Policies")], {
      status: 404,
      body: { detail: "knowledge_base_not_found" },
    });
    await user.click(await screen.findByRole("button", { name: "Delete Policies" }));
    await user.click(screen.getByRole("button", { name: "Confirm delete" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "That knowledge base no longer exists.",
    );
    expect(screen.queryByText("Policies")).not.toBeInTheDocument();
  });

  it("has no accessibility violations", async () => {
    const { view } = setup([kb(1, "Policies")]);
    await screen.findByText("Policies");

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
      await screen.findByRole("heading", { name: "Documents in Policies" });

      if (badge !== "") expect(screen.getByText(badge)).toBeInTheDocument();
      else expect(screen.queryByText(/Shared with you/)).toBeNull();
      expect(screen.queryByRole("button", { name: "Rename Policies" }) !== null).toBe(rename);
      expect(screen.queryByRole("button", { name: "Delete Policies" }) !== null).toBe(remove);
      expect(screen.queryByRole("heading", { name: "Sharing Policies" }) !== null).toBe(sharing);
      expect(screen.queryByLabelText(/Drop files here/) !== null).toBe(upload);
    },
  );
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
