/**
 * Make text safe to show where a user is asked to consent to it. Anything that is invisible,
 * reorders text, or looks like a space but is not one can make text read differently from what it
 * is (a reversed file name, hidden words, Unicode "tag" characters that carry a hidden message),
 * so each such character is replaced with a visible marker like [U+202E].
 *
 * Covered, by Unicode property so the list cannot fall behind: control characters (Cc), format
 * characters (Cf: zero-width, direction overrides and isolates, soft hyphen, tag characters),
 * line and paragraph separators (Zl, Zp), private use (Co) and every space other than the plain
 * one (Zs); plus the characters that render blank although they are letters or symbols (the
 * combining grapheme joiner, Hangul and Khmer fillers, and the blank Braille pattern). Tab,
 * line feed, carriage return and the plain space are kept.
 *
 * No invisible character appears in this file (a test checks that), so the fillers are listed
 * by code point.
 */
const BLANK_LOOKALIKES = [0x034f, 0x115f, 0x1160, 0x17b4, 0x17b5, 0x2800, 0x3164, 0xffa0]
  .map((codePoint) => String.fromCodePoint(codePoint))
  .join("");

const SUSPECT = new RegExp(`[\\p{Cc}\\p{Cf}\\p{Zl}\\p{Zp}\\p{Zs}\\p{Co}${BLANK_LOOKALIKES}]`, "gu");
const KEPT = new Set([" ", "\t", "\n", "\r"]);

export function displaySafe(text: string): string {
  return text.replace(SUSPECT, (char) => {
    if (KEPT.has(char)) return char;
    const hex = (char.codePointAt(0) ?? 0).toString(16).toUpperCase().padStart(4, "0");
    return `[U+${hex}]`;
  });
}
