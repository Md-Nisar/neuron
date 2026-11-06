import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Citation } from "@/lib/stream";
import { accessibilityViolations } from "@/test/axe";
import { jsonResponse } from "@/test/sse";

import { Sources } from "./Sources";

const LEAVE: Citation = {
  doc_id: "0b8f6a52-3c1d-4e7f-9a2b-5c6d7e8f9a0b",
  chunk_id: "1c9e7b63-4d2e-4f80-8b3c-6d7e8f9a0b1c",
  title: "Leave policy",
  headings: ["Annual leave"],
  page_start: 3,
  page_end: 4,
};
const OTHER: Citation = {
  ...LEAVE,
  chunk_id: "2d0f8c74-5e3f-4a91-9c4d-7e8f9a0b1c2d",
  title: "Handbook",
  page_start: 9,
  page_end: 9,
};
const passage = (text: string, extra: Record<string, unknown> = {}) => ({
  doc_id: LEAVE.doc_id,
  kb_id: "9a0b1c2d-3e4f-4a5b-8c6d-7e8f9a0b1c2d",
  chunk_id: LEAVE.chunk_id,
  ordinal: 4,
  text,
  headings: ["Annual leave"],
  page_start: 3,
  page_end: 4,
  neighbours: [],
  ...extra,
});

function setup(answer: () => Response) {
  const fetch = vi.fn<typeof globalThis.fetch>(() => Promise.resolve(answer()));
  const view = render(
    <Sources
      citations={[LEAVE, OTHER]}
      grounded
      deps={{
        apiUrl: "http://127.0.0.1:8000",
        getAccessToken: () => "t",
        onSessionEnded: vi.fn(),
        fetch,
      }}
    />,
  );
  const chip = (n: number) => {
    const found = within(screen.getByRole("list", { name: "Sources" })).getAllByRole("button")[
      n - 1
    ];
    if (found === undefined) throw new Error(`no chip ${String(n)}`);
    return found;
  };
  return { fetch, view, chip, user: userEvent.setup() };
}

const sheet = () => screen.getByRole("region", { name: /^1\. Leave policy/ });

describe("the source sheet", () => {
  it("opens chip 1's passage from the cited page, fetched through the chunk route", async () => {
    const { fetch, chip, user } = setup(() =>
      jsonResponse(200, passage("Everyone gets 25 days of paid leave a year.")),
    );

    await user.click(chip(1));

    expect(
      await within(sheet()).findByText("Everyone gets 25 days of paid leave a year."),
    ).toBeInTheDocument();
    expect(within(sheet()).getByText("pp. 3–4 · Annual leave")).toBeInTheDocument();
    const [url, init] = fetch.mock.calls[0] ?? [];
    expect((url as URL).href).toBe(
      `http://127.0.0.1:8000/v1/knowledge/documents/${LEAVE.doc_id}/chunks/${LEAVE.chunk_id}`,
    );
    expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer t");
    expect(screen.getByRole("button", { expanded: true })).toHaveAttribute(
      "aria-controls",
      sheet().id,
    );
  });

  it.each([404, 403])("says the source is not available, with no text, on %i", async (status) => {
    const { chip, user } = setup(() =>
      jsonResponse(status, { detail: "knowledge_document_not_found" }),
    );

    await user.click(chip(1));

    expect(await within(sheet()).findByText(/Source not available/)).toBeInTheDocument();
    expect(sheet().querySelector("blockquote")).toBeNull();
  });

  it("says loading failed when the server errs or answers with the wrong shape", async () => {
    for (const answer of [() => jsonResponse(500, {}), () => jsonResponse(200, { text: 1 })]) {
      const { chip, user, view } = setup(answer);
      await user.click(chip(1));
      expect(await screen.findByRole("alert")).toHaveTextContent("Could not load the source.");
      view.unmount();
    }
  });

  it("shows markup in a passage as text", async () => {
    const { chip, user } = setup(() =>
      jsonResponse(200, passage('<img src=x onerror="alert(1)"><b>bold</b>')),
    );

    await user.click(chip(1));

    expect(
      await within(sheet()).findByText('<img src=x onerror="alert(1)"><b>bold</b>'),
    ).toBeInTheDocument();
    expect(sheet().querySelector("img, b")).toBeNull();
  });

  it("moves focus to the sheet, and back to its chip when closed", async () => {
    const { chip, user } = setup(() => jsonResponse(200, passage("Text.")));

    await user.click(chip(1));
    expect(within(sheet()).getByRole("heading")).toHaveFocus();
    await user.click(screen.getByRole("button", { name: "Close source" }));

    expect(screen.queryByRole("region")).toBeNull();
    expect(chip(1)).toHaveFocus();
    expect(chip(1)).toHaveAttribute("aria-expanded", "false");
  });

  it("has no accessibility violations while open", async () => {
    const { chip, user, view } = setup(() => jsonResponse(200, passage("Text.")));
    await user.click(chip(1));
    await within(sheet()).findByText("Text.");

    expect(await accessibilityViolations(view.container)).toEqual([]);
  });
});
