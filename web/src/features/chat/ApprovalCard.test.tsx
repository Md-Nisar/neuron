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
  const at = (...codePoints: number[]) => String.fromCodePoint(...codePoints);

  it("leaves ordinary text, including emoji and accents, untouched", () => {
    expect(displaySafe("héllo 😀\n\tok\r\n")).toBe("héllo 😀\n\tok\r\n");
  });

  it("replaces control characters other than tab, newline and carriage return", () => {
    expect(displaySafe(`a${at(0)}b${at(0x1b)}c${at(0x85)}d`)).toBe("a[U+0000]b[U+001B]c[U+0085]d");
  });

  it.each([
    ["zero-width space", 0x200b],
    ["zero-width joiner", 0x200d],
    ["left-to-right mark", 0x200e],
    ["right-to-left override", 0x202e],
    ["left-to-right isolate", 0x2066],
    ["word joiner", 0x2060],
    ["soft hyphen", 0xad],
    ["Arabic letter mark", 0x61c],
    ["byte order mark", 0xfeff],
    ["line separator", 0x2028],
    ["paragraph separator", 0x2029],
    ["Unicode tag letter A (hidden text)", 0xe0041],
    ["tag cancel", 0xe007f],
    ["private use", 0xe000],
    ["no-break space", 0xa0],
    ["em space", 0x2003],
    ["ideographic space", 0x3000],
    ["combining grapheme joiner", 0x34f],
    ["Hangul filler", 0x3164],
    ["halfwidth Hangul filler", 0xffa0],
    ["Khmer inherent vowel", 0x17b4],
    ["blank Braille pattern", 0x2800],
  ])("makes the %s visible", (_name, codePoint) => {
    const shown = displaySafe(`x${at(codePoint)}y`);
    const marker = `[U+${codePoint.toString(16).toUpperCase().padStart(4, "0")}]`;

    expect(shown).toBe(`x${marker}y`);
    expect(shown).not.toContain(at(codePoint));
  });

  it("makes every character of a hidden tag-character message visible, not just the first", () => {
    const hidden = Array.from("ignore")
      .map((letter) => at(0xe0000 + letter.charCodeAt(0)))
      .join("");

    expect(displaySafe(`ok${hidden}`)).toBe(
      "ok[U+E0069][U+E0067][U+E006E][U+E006F][U+E0072][U+E0065]",
    );
  });

  it("keeps a plain space, which is the one space that is not a look-alike", () => {
    expect(displaySafe("a b")).toBe("a b");
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
