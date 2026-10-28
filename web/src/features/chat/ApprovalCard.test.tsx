import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { MAX_ARGS_CHARS } from "./approval";
import { ApprovalCard } from "./ApprovalCard";
import type { ApprovalState, MessageApproval } from "./chatState";
import { displaySafe } from "./displaySafe";

const bidiOverride = String.fromCodePoint(0x202e);
const zeroWidth = String.fromCodePoint(0x200b);

function approval(
  overrides: {
    state?: ApprovalState;
    args?: Record<string, unknown>;
    name?: string;
    allowed?: ("approve" | "reject")[];
    failure?: MessageApproval["failure"];
  } = {},
): MessageApproval {
  return {
    state: overrides.state ?? "pending",
    failure: overrides.failure ?? null,
    payload: {
      request_id: "r1",
      thread_id: "t1",
      approval: {
        approval_id: "a1",
        actions: [
          { name: overrides.name ?? "remember", args: overrides.args ?? { text: "likes tea" } },
        ],
        allowed_decisions: overrides.allowed ?? ["approve", "reject"],
      },
    },
  };
}

function view(state: MessageApproval) {
  const onDecide = vi.fn();
  const result = render(<ApprovalCard approval={state} onDecide={onDecide} />);
  return { onDecide, ...result };
}

describe("ApprovalCard", () => {
  it("shows the tool and its arguments in full, and passes the user's choice on", async () => {
    const { onDecide } = view(approval());

    expect(screen.getByRole("region", { name: "Approval required" })).toBeInTheDocument();
    expect(screen.getByText("remember")).toBeInTheDocument();
    expect(screen.getByText(/"text": "likes tea"/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Approve" }));
    await userEvent.click(screen.getByRole("button", { name: "Reject" }));

    expect(onDecide.mock.calls).toEqual([["approve"], ["reject"]]);
  });

  it("renders hostile arguments and names as text", () => {
    const { container } = view(
      approval({
        name: "<img src=x onerror=alert(1)>",
        args: { html: "<script>alert(2)</script>", link: "[x](javascript:alert(3))" },
      }),
    );

    expect(container.querySelector("script, img, a")).toBeNull();
    expect(container.textContent).toContain("<script>alert(2)</script>");
    expect(container.textContent).toContain("<img src=x onerror=alert(1)>");
  });

  it("makes direction-override and zero-width characters visible instead of obeying them", () => {
    const { container } = view(
      approval({ args: { path: `report${bidiOverride}fdp.exe`, note: `ok${zeroWidth}hidden` } }),
    );

    expect(container.textContent).not.toContain(bidiOverride);
    expect(container.textContent).not.toContain(zeroWidth);
    expect(container.textContent).toContain("report[U+202E]fdp.exe");
    expect(container.textContent).toContain("ok[U+200B]hidden");
  });

  it("cannot approve what it cannot show in full, but can still reject it", async () => {
    const { onDecide } = view(approval({ args: { text: "x".repeat(MAX_ARGS_CHARS + 50) } }));

    expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled();
    expect(screen.getByText(/too long to show in full/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Reject" }));
    expect(onDecide).toHaveBeenCalledWith("reject");
  });

  it("offers only the decisions the server allows", () => {
    view(approval({ allowed: ["reject"] }));

    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    expect(screen.getByRole("button", { name: "Reject" })).toBeInTheDocument();
  });

  it("disables both buttons while the decision is being sent", () => {
    view(approval({ state: "deciding" }));

    expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reject" })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("Sending your decision…");
  });

  it.each([
    ["approved", "You approved this."],
    ["rejected", "You rejected this."],
    [
      "unavailable",
      "This request is no longer available. It may have been decided in another tab, or it expired.",
    ],
  ] as const)("shows the %s outcome and no buttons", (state, text) => {
    view(approval({ state }));

    expect(screen.getByRole("status")).toHaveTextContent(text);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("keeps the buttons and explains a failed attempt in fixed wording", () => {
    view(approval({ failure: { kind: "thread_busy", retryAfterSeconds: null } }));

    expect(screen.getByRole("status")).toHaveTextContent("The previous reply is still finishing.");
    expect(screen.getByRole("button", { name: "Approve" })).toBeEnabled();
  });
});

describe("displaySafe", () => {
  it("leaves ordinary text, including emoji and accents, untouched", () => {
    expect(displaySafe("héllo 😀\n\tok")).toBe("héllo 😀\n\tok");
  });

  it("replaces control characters other than tab and newline", () => {
    expect(displaySafe(`a${String.fromCodePoint(0)}b${String.fromCodePoint(0x1b)}c`)).toBe(
      "a[U+0000]b[U+001B]c",
    );
  });
});

describe("source hygiene", () => {
  it("no web source file contains a raw control, format or line-separator character", () => {
    // \p{Cc} control (incl. NEL), \p{Cf} format (zero-width, bidi), \p{Zl}/\p{Zp} separators.
    const raw = /[\p{Cc}\p{Cf}\p{Zl}\p{Zp}]/u;
    const files = import.meta.glob("/src/**/*.{ts,tsx}", {
      query: "?raw",
      import: "default",
      eager: true,
    });
    const offenders = Object.entries(files)
      .filter(([, text]) => raw.test(text.replace(/[\n\r\t]/g, "")))
      .map(([path]) => path);

    expect(Object.keys(files).length).toBeGreaterThan(20);
    expect(offenders).toEqual([]);
  });
});
