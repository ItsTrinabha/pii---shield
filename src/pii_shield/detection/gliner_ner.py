"""GLiNER zero-shot PII recogniser (local, CPU). Adds recall for names/addresses/IDs the rules and spaCy miss.
Candidates carry detector 'gliner:<label>' so fusion treats them as an independent evidence family."""

from __future__ import annotations

import os
import threading

from ..settings import Settings
from .patterns import Cand

LABELS = {
    "person name": "PERSON", "email address": "EMAIL", "phone number": "PHONE", "street address": "ADDRESS",
    "date of birth": "DATE_OF_BIRTH", "social security number": "SSN", "passport number": "PASSPORT",
    "tax identification number": "TAX_ID", "bank account number": "FINANCIAL_ACCOUNT",
    "credit card number": "FINANCIAL_ACCOUNT", "ip address": "IP_ADDRESS", "employee id": "EMPLOYEE_ID",
}
# score -> confidence: conf = a + b * score, capped. Hand-set from the sample documents (see docs/RESULTS.md), not learned.
CAL = {"PERSON": (0.50, 0.45), "ADDRESS": (0.45, 0.45)}
CAL_DEFAULT = (0.40, 0.45)

_lock = threading.Lock()
_MODEL: dict[str, object] = {}


def _model(name: str):
    with _lock:
        if name not in _MODEL:
            os.environ.setdefault("HF_HUB_OFFLINE", "1")  # weights are fetched once by scripts/fetch_models.py, never at scan time
            import torch
            from gliner import GLiNER

            # 16 threads on a 16-core box ran 3.5x slower than 8 (oversubscription), identical output
            torch.set_num_threads(max(1, min(8, (os.cpu_count() or 2) // 2)))

            _MODEL[name] = GLiNER.from_pretrained(name)
        return _MODEL[name]


def _split(chunk, max_chars: int = 1000):
    """Re-window a NER chunk at block boundaries so each piece fits the model's input length."""
    text, spans = chunk
    if len(text) <= max_chars:
        return [chunk]
    out, cur, base = [], [], spans[0][1]
    for sp in spans:
        if cur and sp[2] - base > max_chars:
            out.append((text[base:cur[-1][2]], [(i, s - base, e - base) for i, s, e in cur]))
            cur, base = [], sp[1]
        cur.append(sp)
    out.append((text[base:cur[-1][2]], [(i, s - base, e - base) for i, s, e in cur]))
    return out


def run_gliner(chunks: list[tuple[str, list[tuple[int, int, int]]]], settings: Settings) -> dict[int, list[Cand]]:
    import bisect

    out: dict[int, list[Cand]] = {}
    m = _model(settings.gliner_model)
    chunks = [c for ch in chunks for c in _split(ch)]  # the model truncates at 384 words
    all_ents = m.batch_predict_entities([c[0] for c in chunks], list(LABELS), threshold=settings.gliner_threshold, batch_size=8)
    for (ctext, spans), ents in zip(chunks, all_ents):
        starts = [s for _, s, _ in spans]
        for ent in ents:
            typ = LABELS.get(ent["label"])
            i = bisect.bisect_right(starts, ent["start"]) - 1
            if not typ or i < 0:
                continue
            bidx, bs, be = spans[i]
            if ent["end"] > be:
                continue
            a, b = CAL.get(typ, CAL_DEFAULT)
            out.setdefault(bidx, []).append(Cand(typ, ent["start"] - bs, ent["end"] - bs, min(0.95, a + b * ent["score"]),
                                                 f"gliner:{ent['label'].replace(' ', '-')}"))
    return out
