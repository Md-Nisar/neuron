import { describe, expect, it } from "vitest";

import { characterCount, checkDraft, DEFAULT_MAX_PROMPT_CHARS, maxPromptChars } from "./limits";

describe("checkDraft", () => {
  it("accepts ordinary text and trims it, like the server", () => {
    expect(checkDraft("  hello \n")).toEqual({ text: "hello", problem: null });
  });

  it("allows tab, newline and carriage return inside the message", () => {
    expect(checkDraft("a\tb\nc\r\nd").problem).toBeNull();
  });

  it.each(["", "   ", "\n\t "])("refuses an empty message (%j)", (draft) => {
    expect(checkDraft(draft).problem).toBe("empty");
  });

  it.each(["a\u0000b", "a\u0007b", "a\u001bb", "a\u007fb", "a\u0085b", "a\u009fb"])(
    "refuses control characters (%j)",
    (draft) => {
      expect(checkDraft(draft).problem).toBe("control_characters");
    },
  );

  it("counts the limit after trimming and at the exact boundary", () => {
    expect(checkDraft(` ${"a".repeat(100)} `, 100).problem).toBeNull();
    expect(checkDraft("a".repeat(101), 100).problem).toBe("too_long");
  });

  it("counts code points like the server, so an emoji is one character", () => {
    expect(characterCount("😀😀")).toBe(2);
    expect(checkDraft("😀".repeat(100), 100).problem).toBeNull();
    expect(checkDraft("😀".repeat(101), 100).problem).toBe("too_long");
  });
});

describe("maxPromptChars", () => {
  it("defaults to the server's default", () => {
    expect(maxPromptChars({})).toBe(DEFAULT_MAX_PROMPT_CHARS);
    expect(DEFAULT_MAX_PROMPT_CHARS).toBe(12_000);
  });

  it("reads a valid setting and ignores nonsense", () => {
    expect(maxPromptChars({ VITE_MAX_PROMPT_CHARS: "5000" })).toBe(5000);
    for (const bad of ["abc", "50", "999999", "1.5", ""]) {
      expect(maxPromptChars({ VITE_MAX_PROMPT_CHARS: bad })).toBe(DEFAULT_MAX_PROMPT_CHARS);
    }
  });
});
