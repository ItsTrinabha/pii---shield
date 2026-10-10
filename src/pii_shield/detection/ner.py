"""Presidio + spaCy wrapper. NER runs over context windows (several blocks at a time) because a lone table cell such as
'Marc Otani' gives a language model almost nothing to work with, while its neighbours (role, group, email) do."""

from __future__ import annotations

import bisect
import threading
from dataclasses import dataclass

from ..settings import Settings
from .patterns import Cand


@dataclass
class NBlock:
    idx: int
    id: str
    text: str  # normalised text
    unit_key: str


_PRESIDIO_MAP = {
    "PERSON": "PERSON",
    "EMAIL_ADDRESS": "EMAIL",
    "PHONE_NUMBER": "PHONE",
    "US_SSN": "SSN",
    "CREDIT_CARD": "FINANCIAL_ACCOUNT",
    "IBAN_CODE": "FINANCIAL_ACCOUNT",
    "IP_ADDRESS": "IP_ADDRESS",
    "US_PASSPORT": "PASSPORT",
    "UK_NHS": None,
}
_ENTITIES = [k for k, v in _PRESIDIO_MAP.items() if v]

_lock = threading.Lock()
_ENGINE: dict[str, object] = {}


def _engine(model: str):
    with _lock:
        if model not in _ENGINE:
            # The gateway must never open a network connection while handling documents: force tldextract (used by
            # Presidio's e-mail/URL recognisers) onto its bundled suffix list instead of fetching one.
            import tldextract
            import tldextract.tldextract as _tx

            _tx.TLD_EXTRACTOR = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)

            from presidio_analyzer import AnalyzerEngine, BatchAnalyzerEngine, RecognizerRegistry
            from presidio_analyzer.nlp_engine import NlpEngineProvider

            nlp = NlpEngineProvider(
                nlp_configuration={"nlp_engine_name": "spacy", "models": [{"lang_code": "en", "model_name": model}]}
            ).create_engine()
            reg = RecognizerRegistry()
            reg.load_predefined_recognizers(nlp_engine=nlp, languages=["en"])
            analyzer = AnalyzerEngine(nlp_engine=nlp, registry=reg, supported_languages=["en"])
            _ENGINE[model] = BatchAnalyzerEngine(analyzer_engine=analyzer)
        return _ENGINE[model]


def build_chunks(nblocks: list[NBlock], max_chars: int = 4000) -> list[tuple[str, list[tuple[int, int, int]]]]:
    """Group consecutive blocks of the same unit into windows. Returns [(text, [(block_idx, start, end), ...])]."""
    chunks: list[tuple[str, list[tuple[int, int, int]]]] = []
    buf: list[str] = []
    spans: list[tuple[int, int, int]] = []
    pos = 0
    cur_key = None

    def flush():
        nonlocal buf, spans, pos
        if spans:
            chunks.append(("".join(buf), spans))
        buf, spans, pos = [], [], 0

    for nb in nblocks:
        if not nb.text.strip():
            continue
        if nb.unit_key != cur_key or pos + len(nb.text) + 1 > max_chars:
            flush()
            cur_key = nb.unit_key
        text = nb.text
        if len(text) > max_chars:  # very long single block: window it
            for off in range(0, len(text), max_chars):
                flush()
                piece = text[off:off + max_chars]
                chunks.append((piece, [(nb.idx, off, off + len(piece))]))
            continue
        spans.append((nb.idx, pos, pos + len(text)))
        buf.append(text + "\n")
        pos += len(text) + 1
    flush()
    return chunks


def run_ner(nblocks: list[NBlock], settings: Settings) -> dict[int, list[Cand]]:
    """Return Presidio/spaCy candidates keyed by block index, in block-local normalised offsets."""
    out: dict[int, list[Cand]] = {}
    if not settings.use_ner or not nblocks:
        return out
    eng = _engine(settings.ner_model)
    chunks = build_chunks(nblocks)
    texts = [c[0] for c in chunks]
    results = eng.analyze_iterator(texts, language="en", batch_size=16, entities=_ENTITIES, score_threshold=0.3)
    for (ctext, spans), res in zip(chunks, results):
        starts = [s for _, s, _ in spans]
        for r in res:
            typ = _PRESIDIO_MAP.get(r.entity_type)
            if not typ:
                continue
            i = bisect.bisect_right(starts, r.start) - 1
            if i < 0:
                continue
            bidx, bs, be = spans[i]
            if r.end > be:  # crosses a block boundary -> ignore (cannot be one entity inside one block)
                continue
            rec = (r.recognition_metadata or {}).get("recognizer_name", r.entity_type) if hasattr(r, "recognition_metadata") else r.entity_type
            if typ == "PERSON":
                conf = 0.62  # spaCy PERSON is useful but false-positive prone; rules below refine it
            else:
                conf = min(0.9, 0.45 + 0.5 * float(r.score))
            out.setdefault(bidx, []).append(Cand(typ, r.start - bs, r.end - bs, conf, f"presidio:{rec}"))
    return out
