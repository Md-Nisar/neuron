/**
 * Make text safe to show where a user is asked to consent to it. Control characters, zero-width
 * and bidirectional-override characters can make text read differently from what it is (a
 * reversed file name, hidden words), so they are replaced with a visible marker like U+202E.
 *
 * The ranges are written as escapes on purpose: this file must contain no invisible character
 * (a test checks that).
 */
/* eslint-disable no-control-regex */
const INVISIBLE =
  /[\u0000-\u0008\u000b-\u000c\u000e-\u001f\u007f-\u009f\u200b-\u200f\u202a-\u202e\u2060-\u2069\ufeff]/gu;
/* eslint-enable no-control-regex */

export function displaySafe(text: string): string {
  return text.replace(INVISIBLE, (char) => {
    const hex = (char.codePointAt(0) ?? 0).toString(16).toUpperCase().padStart(4, "0");
    return `[U+${hex}]`;
  });
}
