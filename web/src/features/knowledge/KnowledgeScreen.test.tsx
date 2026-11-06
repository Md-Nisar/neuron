import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { accessibilityViolations } from "@/test/axe";
import { jsonResponse } from "@/test/sse";

import { KnowledgeScreen } from "./KnowledgeScreen";

const kb = (n: number, name: string, processing = "hosted") => ({
  kb_id: `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`,
  name,
  processing,
  created_at: "2026-11-01T10:00:00Z",
});

/** A fetch that answers `GET` with the bases and `POST` with `created` (or `failure`). */
function setup(bases: unknown[], post?: { status: number; body: unknown }) {
  const fetch = vi.fn<typeof globalThis.fetch>((_input, init) =>
    Promise.resolve(
      init?.method === "POST"
        ? jsonResponse(post?.status ?? 201, post?.body)
        : jsonResponse(200, { bases }),
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
    await user.click(screen.getByRole("button", { name: "Create" }));

    expect(await screen.findByText("Contracts")).toBeInTheDocument();
    const [, init] = fetch.mock.calls[1] ?? [];
    expect(JSON.parse(init?.body as string)).toEqual({
      name: "Contracts",
      processing: "self_hosted",
    });
    expect(screen.getByLabelText("New knowledge base")).toHaveValue("");
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

  it("has no accessibility violations", async () => {
    const { view } = setup([kb(1, "Policies")]);
    await screen.findByText("Policies");

    expect(await accessibilityViolations(view.container)).toEqual([]);
  });
});
