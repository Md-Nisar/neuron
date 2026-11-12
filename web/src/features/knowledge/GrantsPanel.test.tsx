import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { accessibilityViolations } from "@/test/axe";
import { jsonResponse } from "@/test/sse";

import { GrantsPanel, MAX_GRANTS } from "./GrantsPanel";
import type { Grant } from "./parse";

const KB = "0b6f1c1e-6c8e-4c36-9d2b-6a1f2f3e4d5c";

/** A fetch that answers `GET` with `grants` and a `PUT` with `reply` or else what it was sent. */
function setup(grants: Grant[], reply?: { status: number; body: unknown }) {
  const fetch = vi.fn<typeof globalThis.fetch>((_, init) =>
    Promise.resolve(
      init?.method === "PUT"
        ? ((reply && jsonResponse(reply.status, reply.body)) ??
            jsonResponse(200, JSON.parse(init.body as string)))
        : jsonResponse(200, { grants }),
    ),
  );
  const user = userEvent.setup();
  const view = render(
    <GrantsPanel
      deps={{
        apiUrl: "http://127.0.0.1:8000",
        getAccessToken: () => "t",
        onSessionEnded: vi.fn(),
        fetch,
      }}
      base={{ kb_id: KB, name: "Policies", processing: "hosted", created_at: "", access: "owner" }}
    />,
  );
  const sent = () =>
    fetch.mock.calls
      .filter(([, init]) => init?.method === "PUT")
      .map(([, init]) => (JSON.parse(init?.body as string) as { grants: Grant[] }).grants);
  return { fetch, user, view, sent };
}

describe("sharing a knowledge base", () => {
  it("lists each role as text with its access, and is accessible", async () => {
    const hostile = '<img src=x onerror="alert(1)">';
    const { view } = setup([
      { role: "finance", access: "read" },
      { role: hostile, access: "admin" },
    ]);
    const list = await screen.findByRole("list", { name: "Roles with access to Policies" });
    expect(screen.getByText(hostile)).toBeInTheDocument();
    expect(list.querySelector("img")).toBeNull();
    expect(screen.getByRole("combobox", { name: "Access for finance" })).toHaveValue("read");
    expect(screen.getByRole("combobox", { name: `Access for ${hostile}` })).toHaveValue("admin");
    expect(await accessibilityViolations(view.container)).toEqual([]);
  });

  it("shares with a role, changes its access and stops sharing, each saved whole", async () => {
    const { user, sent } = setup([]);
    await screen.findByText("Not shared with any role.");

    await user.type(screen.getByLabelText("Role"), "  finance ");
    await user.selectOptions(screen.getByLabelText("Access"), "write");
    await user.click(screen.getByRole("button", { name: "Share" }));
    await screen.findByRole("combobox", { name: "Access for finance" });
    expect(screen.getByLabelText("Role")).toHaveValue("");

    await user.selectOptions(screen.getByRole("combobox", { name: "Access for finance" }), "admin");
    await waitFor(() => {
      expect(sent()).toHaveLength(2);
    });
    await user.click(screen.getByRole("button", { name: "Stop sharing with finance" }));
    await screen.findByText("Not shared with any role.");

    expect(sent()).toEqual([
      [{ role: "finance", access: "write" }],
      [{ role: "finance", access: "admin" }],
      [],
    ]);
    expect(screen.getByRole("heading", { name: "Sharing Policies" })).toHaveFocus();
  });

  it.each([
    ["an empty role", "   ", [], "Use 1 to 200 characters."],
    ["a role too long", "x".repeat(201), [], "Use 1 to 200 characters."],
    [
      "a role already there",
      "finance",
      [{ role: "finance", access: "read" as const }],
      "That role already has access. Change it in the list.",
    ],
    [
      "one role too many",
      "one-more",
      Array.from({ length: MAX_GRANTS }, (_, n) => ({
        role: `r${String(n)}`,
        access: "read" as const,
      })),
      "A knowledge base can be shared with at most 50 roles.",
    ],
  ])("refuses %s without a call", async (_, role, grants: Grant[], message) => {
    const { user, sent } = setup(grants);
    await user.click(await screen.findByLabelText("Role"));
    await user.paste(role);
    await user.click(screen.getByRole("button", { name: "Share" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(sent()).toEqual([]);
  });

  it.each([
    [422, { detail: [] }, "That role can't be used. Use 1 to 200 visible characters."],
    [
      403,
      { detail: "knowledge_access_denied" },
      "Your access to this knowledge base doesn't allow that.",
    ],
  ])("says why the server refused a change (%i), keeping the list", async (status, body, text) => {
    const { user } = setup([{ role: "legal", access: "read" }], { status, body });
    await user.type(await screen.findByLabelText("Role"), "finance");
    await user.click(screen.getByRole("button", { name: "Share" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(text);
    expect(screen.getByLabelText("Role")).toHaveValue("finance");
    expect(screen.getByRole("combobox", { name: "Access for legal" })).toBeInTheDocument();
  });
});
