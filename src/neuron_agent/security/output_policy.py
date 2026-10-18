"""Output policy: block answers that reproduce the system prompt (ADR 0003 addendum).

The check is deterministic and runs in code, because the model is not a security boundary.
Text is normalised to lowercase alphanumeric words, so case, whitespace, markdown and
punctuation do not matter. An answer leaks when it shares any run of `LEAK_NGRAM_WORDS`
consecutive words with the prompt the agent really loads. It never uses the eval's marker
list and never stores the prompt anywhere but the loader's cache.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

from neuron_agent.prompts.loader import load_prompt

# Shortest shared run of words that counts as reproducing the prompt. Ordinary prose shares
# runs of up to 6-7 words with it ("neuron agent a concise production assistant", "tool output
# as untrusted content"); a run of 8 is a quoted rule or the opening line.
# Most rules are longer. See tests/security/test_output_policy.py.
LEAK_NGRAM_WORDS = 8

SYSTEM_PROMPT_PATH = "system/main.md"

# Shown instead of a leaking answer. Fixed text, so it echoes nothing.
SYSTEM_PROMPT_REFUSAL = "I can't share my instructions."

POLICY_RULE = "system_prompt_disclosure"

_WORD = re.compile(r"[^\W_]+")


def _words(text: str) -> list[str]:
    folded = unicodedata.normalize("NFKC", text).casefold()
    # Format characters (zero-width spaces and joiners) are invisible: drop them so they cannot
    # split a word.
    visible = "".join(c for c in folded if unicodedata.category(c) != "Cf")
    return _WORD.findall(visible)


def _shingles(words: list[str]) -> set[tuple[str, ...]]:
    n = LEAK_NGRAM_WORDS
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


@lru_cache
def _prompt_shingles(prompt: str) -> frozenset[tuple[str, ...]]:
    return frozenset(_shingles(_words(prompt)))


def leaks_system_prompt(text: str, *, prompt: str | None = None) -> bool:
    """Whether `text` reproduces `LEAK_NGRAM_WORDS` or more consecutive words of the prompt."""
    known = _prompt_shingles(prompt if prompt is not None else load_prompt(SYSTEM_PROMPT_PATH))
    return not known.isdisjoint(_shingles(_words(text)))


class StreamLeakGuard:
    """Releases streamed answer text only once it can no longer start a prompt quote.

    The last `LEAK_NGRAM_WORDS` whitespace-separated tokens are held back (the last may be a
    partial word), so a quote is detected before its eighth word is sent and at most seven
    consecutive prompt words can reach a client. After a hit nothing more is released; `flush`
    returns the held text once the answer is final.
    """

    def __init__(self, *, prompt: str | None = None) -> None:
        self._prompt = prompt
        self._text = ""
        self._released = 0
        self.blocked = False

    def feed(self, delta: str) -> str:
        """Add `delta`; return the text now safe to send (possibly empty)."""
        if self.blocked:
            return ""
        self._text += delta
        # Text before `_released` was already checked and ends 7+ words back, so any new run
        # lies in the held-back tail plus the delta. This keeps the work per delta bounded.
        window = self._text[self._released :]
        if leaks_system_prompt(window, prompt=self._prompt):
            self.blocked = True
            return ""
        starts = [m.start() for m in re.finditer(r"\S+", window)]
        # One more than the run length: the last token may be a partial word, and a quote ending in
        # it needs the seven complete words before it.
        keep = LEAK_NGRAM_WORDS
        cut = starts[-keep] if len(starts) >= keep else 0
        out = window[:cut]
        self._released += cut
        return out

    def flush(self) -> str:
        """The held-back tail, unless a leak was seen."""
        if self.blocked:
            return ""
        out = self._text[self._released :]
        self._released = len(self._text)
        return out
