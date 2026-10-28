/**
 * The API's input rules for a message (`security/input_policy.py`, `Settings.max_prompt_chars`),
 * mirrored so the user gets an answer before sending. The server stays authoritative: it counts
 * characters after trimming and refuses control characters other than tab and line breaks.
 */
export const DEFAULT_MAX_PROMPT_CHARS = 12_000;

export type DraftProblem = "empty" | "too_long" | "control_characters";

// Unicode category Cc, minus tab, LF and CR.
// eslint-disable-next-line no-control-regex
const DISALLOWED_CONTROL = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f]/;

export function maxPromptChars(env: { VITE_MAX_PROMPT_CHARS?: string | undefined }): number {
  const configured = Number(env.VITE_MAX_PROMPT_CHARS);
  return Number.isInteger(configured) && configured >= 100 && configured <= 200_000
    ? configured
    : DEFAULT_MAX_PROMPT_CHARS;
}

/** Count characters the way the server does (code points, not UTF-16 units). */
export function characterCount(text: string): number {
  return Array.from(text).length; // code points, like Python's len()
}

export function checkDraft(
  raw: string,
  max: number = DEFAULT_MAX_PROMPT_CHARS,
): { text: string; problem: DraftProblem | null } {
  const text = raw.trim();
  if (text === "") return { text, problem: "empty" };
  if (characterCount(text) > max) return { text, problem: "too_long" };
  if (DISALLOWED_CONTROL.test(text)) return { text, problem: "control_characters" };
  return { text, problem: null };
}
