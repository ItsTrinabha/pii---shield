"""Document-level consistency: once a value is found anywhere, mask every other occurrence of it in the document.
Full values of any type, plus distinctive single name parts (surname / first name) of detected people."""

from __future__ import annotations

import re

from ..models import Block
from .engine import RawFinding


def _rare(tok: str) -> bool:
    from wordfreq import zipf_frequency

    return len(tok) >= 5 and tok[0].isupper() and tok.isalpha() and zipf_frequency(tok.lower(), "en") < 3.5


def propagate(blocks: list[Block], found: list[RawFinding]) -> list[RawFinding]:
    values: dict[str, tuple[str, str]] = {}  # needle -> (type, key)
    for f in found:
        v = f.block.text[f.start:f.end].strip()
        if len(v) < 6 or f.confidence < 0.6 or f.detectors == ["propagate"]:
            continue
        if f.type != "PERSON" or " " in v:  # a lone name part is only propagated when it is rare (below)
            values.setdefault(v, (f.type, f.key))
        if f.type == "PERSON":
            for t in re.findall(r"[A-Za-z][A-Za-z'\-]+", v):
                if _rare(t):
                    values.setdefault(t, ("PERSON", f.key))
    if not values:
        return []
    pat = re.compile(r"(?<![\w])(?:" + "|".join(re.escape(v) for v in sorted(values, key=len, reverse=True)) + r")(?![\w])")
    taken: dict[str, list[tuple[int, int]]] = {}
    for f in found:
        taken.setdefault(f.block.id, []).append((f.start, f.end))
    out: list[RawFinding] = []
    for b in blocks:
        spans = taken.get(b.id, [])
        for m in pat.finditer(b.text):
            if any(m.start() < e and s < m.end() for s, e in spans):
                continue
            typ, key = values[m.group(0)]
            out.append(RawFinding(block=b, type=typ, start=m.start(), end=m.end(), confidence=0.7, detectors=["propagate"],
                                  key=key, ocr_derived=(b.source == "ocr"), note="same value found elsewhere in the document"))
    return out
