/**
 * Make text safe to show where a user is asked to consent to it. Anything invisible, anything
 * that reorders text, and anything that looks like a space but is not one can make text read
 * differently from what it is (a reversed file name, hidden words, Unicode "tag" or variation
 * selector characters that carry a hidden message). Each such character is replaced with a
 * visible marker like [U+202E].
 *
 * This is an allowlist, so a new kind of invisible character is shown by default: only letters,
 * marks, numbers, punctuation and symbols are passed through, together with the plain space, tab,
 * line feed and carriage return. Everything else is marked: control, format, separator, private
 * use, unassigned and surrogate code points, and every space but the plain one. On top of that,
 * Unicode's own `Default_Ignorable_Code_Point` set is marked even where it falls inside a passed
 * category (variation selectors, the combining grapheme joiner, Hangul and Khmer fillers), plus
 * the blank Braille pattern, which is a symbol that renders as nothing.
 *
 * Cost: an emoji written with a variation selector (a heart with U+FE0F) shows the marker. For
 * text a person is asked to approve, noise is better than hidden characters.
 *
 * No invisible character appears in this file (a test checks that), so the blank Braille pattern
 * is built from its code point.
 */
const BLANK_BRAILLE = String.fromCodePoint(0x2800);

const SUSPECT = new RegExp(
  `[^\\p{L}\\p{M}\\p{N}\\p{P}\\p{S} \\t\\n\\r]|\\p{Default_Ignorable_Code_Point}|${BLANK_BRAILLE}`,
  "gu",
);

export function displaySafe(text: string): string {
  return text.replace(SUSPECT, (char) => {
    const hex = (char.codePointAt(0) ?? 0).toString(16).toUpperCase().padStart(4, "0");
    return `[U+${hex}]`;
  });
}
