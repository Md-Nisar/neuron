import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { accessibilityViolations } from "@/test/axe";
import { jsonResponse } from "@/test/sse";

import { KnowledgePicker, MAX_SELECTED, RETRY_MS } from "./KnowledgePicker";

const kb = (n: number) => ({
  kb_id: `0b6f1c1e-6c8e-4c36-9d2b-${n.toString(16).padStart(12, "0")}`,
  name: `Base ${String(n)}`,
  processing: "hosted",
  created_at: "",
  access: "owner",
});

function setup(lists: Response[], initial: string[] = []) {
  let call = 0;
  const fetch = vi.fn<typeof globalThis.fetch>(() =>
    Promise.resolve((lists[Math.min(call++, lists.length - 1)] ?? jsonResponse(500, {})).clone()),
  );
  const changes: string[][] = [];
  function Harness({ active = true }: { active?: boolean }) {
    const [selected, setSelected] = useState(initial);
    return (
      <KnowledgePicker
        deps={{
          apiUrl: "http://127.0.0.1:8000",
          getAccessToken: () => "t",
          onSessionEnded: vi.fn(),
          fetch,
        }}
        selected={selected}
        onChange={(ids) => {
          changes.push(ids);
          setSelected(ids);
        }}
        active={active}
      />
    );
  }
  const view = render(<Harness />);
  /** Leave the chat for another screen and come back, as the app's navigation does. */
  const revisit = () => {
    view.rerender(<Harness active={false} />);
    view.rerender(<Harness />);
  };
  return { view, changes, fetch, revisit, user: userEvent.setup() };
}

const toggle = () => screen.findByRole("button", { name: /Knowledge to search/ });

describe("the knowledge picker", () => {
  it("shows nothing when knowledge is off, not permitted or has no base", async () => {
    for (const answer of [
      jsonResponse(404, { detail: "knowledge_disabled" }),
      jsonResponse(403, {}),
      jsonResponse(200, { bases: [] }),
    ]) {
      const { view } = setup([answer]);
      await new Promise((resolve) => setTimeout(resolve, 0));
      expect(screen.queryByRole("button")).toBeNull();
      view.unmount();
    }
  });

  it("searches all bases until some are chosen", async () => {
    const { changes, user } = setup([jsonResponse(200, { bases: [kb(1), kb(2)] })]);

    expect(await toggle()).toHaveTextContent("All knowledge");
    await user.click(await toggle());
    await user.click(screen.getByRole("checkbox", { name: "Base 2" }));

    expect(changes.at(-1)).toEqual([kb(2).kb_id]);
    expect(await toggle()).toHaveTextContent("1 of 2 bases");
  });

  it(`allows at most ${String(MAX_SELECTED)}`, async () => {
    const bases = Array.from({ length: MAX_SELECTED + 1 }, (_, i) => kb(i + 1));
    const chosen = bases.slice(0, MAX_SELECTED).map((base) => base.kb_id);
    const { user, view } = setup([jsonResponse(200, { bases })], chosen);

    await user.click(await toggle());

    expect(
      await screen.findByRole("checkbox", { name: `Base ${String(MAX_SELECTED + 1)}` }),
    ).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "Base 1" })).toBeEnabled();
    expect(await accessibilityViolations(view.container)).toEqual([]);
  });

  it("drops a chosen base that has since been deleted", async () => {
    const { changes, user } = setup(
      [jsonResponse(200, { bases: [kb(1), kb(2)] }), jsonResponse(200, { bases: [kb(1)] })],
      [kb(1).kb_id, kb(2).kb_id],
    );

    await user.click(await toggle());

    await vi.waitFor(() => {
      expect(changes.at(-1)).toEqual([kb(1).kb_id]);
    });
  });

  it("appears when the first base is made on another screen, without a reload", async () => {
    const { fetch, revisit } = setup([
      jsonResponse(200, { bases: [] }),
      jsonResponse(200, { bases: [kb(1)] }),
    ]);
    await vi.waitFor(() => {
      expect(fetch).toHaveBeenCalledTimes(1);
    });
    expect(screen.queryByRole("button")).toBeNull();

    revisit();

    expect(await toggle()).toHaveTextContent("All knowledge");
  });

  it("drops a base deleted on another screen before the next question, unopened", async () => {
    const { changes, revisit } = setup(
      [jsonResponse(200, { bases: [kb(1), kb(2)] }), jsonResponse(200, { bases: [kb(1)] })],
      [kb(2).kb_id],
    );
    expect(await toggle()).toHaveTextContent("1 of 2 bases");

    revisit();

    await vi.waitFor(() => {
      expect(changes.at(-1)).toEqual([]);
    });
    expect(await toggle()).toHaveTextContent("All knowledge");
  });

  it("keeps the list and the choice in view when a refresh fails", async () => {
    const { user } = setup(
      [jsonResponse(200, { bases: [kb(1), kb(2)] }), jsonResponse(500, {})],
      [kb(1).kb_id],
    );

    await user.click(await toggle());
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(await toggle()).toHaveTextContent("1 of 2 bases");
    expect(screen.getByRole("checkbox", { name: "Base 1" })).toBeChecked();
  });

  it("tries again when its first load is rate limited, and appears", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      setup([jsonResponse(429, { detail: "rate_limited" }), jsonResponse(200, { bases: [kb(1)] })]);
      await act(() => vi.advanceTimersByTimeAsync(0));
      expect(screen.queryByRole("button")).toBeNull();

      await act(() => vi.advanceTimersByTimeAsync(RETRY_MS));

      expect(await toggle()).toHaveTextContent("All knowledge");
    } finally {
      vi.useRealTimers();
    }
  });

  it("does not retry when knowledge is off or not permitted", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const { fetch } = setup([jsonResponse(403, {}), jsonResponse(200, { bases: [kb(1)] })]);
      await act(() => vi.advanceTimersByTimeAsync(RETRY_MS * 4));
      expect(fetch).toHaveBeenCalledTimes(1);
      expect(screen.queryByRole("button")).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });
});
