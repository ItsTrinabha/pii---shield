"""Text normalisation with an exact offset map back to the original text.

Detection runs on normalised text so that evasion tricks (zero-width characters, full-width digits, Cyrillic
look-alikes, odd spaces) cannot hide PII. Masking is applied to the ORIGINAL text through the map."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

# Latin look-alikes commonly used to dodge pattern matchers (1:1 mappings keep offsets simple)
_CONFUSABLES = {
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ј": "j", "ѕ": "s", "һ": "h", "ԁ": "d",
    "ɡ": "g", "ο": "o", "ν": "v", "ι": "i", "κ": "k", "ρ": "p", "τ": "t", "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H",
    "Ι": "I", "Κ": "K", "Μ": "M", "Ν": "N", "Ο": "O", "Ρ": "P", "Τ": "T", "Χ": "X", "Υ": "Y", "А": "A", "В": "B", "Е": "E",
    "К": "K", "М": "M", "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T", "Х": "X", "І": "I", "Ј": "J", "Ѕ": "S",
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "−": "-", "﹣": "-", "－": "-",
    "’": "'", "‘": "'", "ʼ": "'",
}


@dataclass
class NormText:
    text: str
    to_orig: list[int]  # to_orig[i] = index in original text of normalised char i
    orig_len: int

    def span_to_orig(self, s: int, e: int) -> tuple[int, int]:
        if not self.to_orig:
            return 0, 0
        s = max(0, min(s, len(self.to_orig) - 1))
        e = max(s + 1, min(e, len(self.to_orig)))
        return self.to_orig[s], self.to_orig[e - 1] + 1


def normalize(original: str) -> NormText:
    out: list[str] = []
    mp: list[int] = []
    for i, ch in enumerate(original):
        cat = unicodedata.category(ch)
        if cat == "Cf" or ch in ("­", "​", "‌", "‍", "⁠", "﻿"):
            continue  # zero-width / formatting characters are dropped
        if ch in _CONFUSABLES:
            out.append(_CONFUSABLES[ch])
            mp.append(i)
            continue
        if ch in ("\t", "\r", "\v", "\f", " ", " ", " ", "　") or cat == "Zs":
            out.append(" ")
            mp.append(i)
            continue
        n = unicodedata.normalize("NFKC", ch)
        if n == ch:
            out.append(ch)
            mp.append(i)
        else:
            for c in n:
                out.append(c)
                mp.append(i)
    return NormText("".join(out), mp, len(original))
