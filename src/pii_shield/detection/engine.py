"""Hybrid detection engine: deterministic patterns + Presidio/spaCy NER + names layer, then fusion."""

from __future__ import annotations

import re
import time
from itertools import pairwise
from dataclasses import dataclass, field

from ..models import Block, ExtractedDocument
from ..settings import Settings, allowlist
from .fusion import fuse
from .names import ln, detect_people
from .ner import NBlock, run_ner
from .normalize import NormText, normalize
from .patterns import Cand, phone_split_cands, run_patterns, split_phone_pair

_ORGS = None


@dataclass
class RawFinding:
    block: Block
    type: str
    start: int  # original-text offsets
    end: int
    confidence: float
    detectors: list[str]
    key: str
    ocr_derived: bool
    note: str = ""


@dataclass
class DetectionResult:
    findings: list[RawFinding] = field(default_factory=list)
    review_candidates: list[RawFinding] = field(default_factory=list)  # below mask threshold, above review band
    norms: dict[str, NormText] = field(default_factory=dict)
    timings: dict[str, float] = field(default_factory=dict)
    stats: dict[str, int] = field(default_factory=dict)
    person_registry: object | None = None


def _unit_key(b: Block) -> str:
    loc = b.locator
    if loc.unit in ("page", "slide"):
        return f"{loc.unit}:{loc.index}"
    return f"{loc.unit}:{loc.index}:{loc.part.split(' ')[0] if loc.unit in ('metadata', 'hyperlink', 'sweep') else ''}"


def _is_allowlisted(text: str) -> bool:
    global _ORGS
    if _ORGS is None:
        _ORGS = {o.lower() for o in allowlist()["organisations"]}
    return text.strip().lower() in _ORGS


def detect_document(doc: ExtractedDocument, settings: Settings) -> DetectionResult:
    res = DetectionResult()
    t0 = time.time()
    norms: list[NormText] = []
    nblocks: list[NBlock] = []
    for i, b in enumerate(doc.blocks):
        nt = normalize(b.text)
        norms.append(nt)
        res.norms[b.id] = nt
        nblocks.append(NBlock(idx=i, id=b.id, text=nt.text, unit_key=_unit_key(b)))
    res.timings["normalize"] = time.time() - t0

    t0 = time.time()
    per_block: dict[int, list[Cand]] = {}
    email_cands: dict[int, list[Cand]] = {}
    for nb in nblocks:
        cs = run_patterns(nb.text)
        per_block[nb.idx] = cs
        em = [c for c in cs if c.type == "EMAIL"]
        if em:
            email_cands[nb.idx] = em
    # a number whose prefix ends one OCR paragraph and whose continuation starts the next one on the same page
    for na, nb in pairwise(nblocks):
        if na.unit_key != nb.unit_key:
            continue
        pair = split_phone_pair(na.text, nb.text)
        if pair:
            (hs, he), (ts, te) = pair
            h, t = phone_split_cands((hs, he, na.text[hs:he]), (ts, te, nb.text[ts:te]))
            per_block[na.idx].append(h)
            per_block[nb.idx].append(t)
    res.timings["patterns"] = time.time() - t0

    t0 = time.time()
    ner = run_ner(nblocks, settings)
    res.timings["ner"] = time.time() - t0
    for bidx, cs in ner.items():
        for c in cs:
            if c.type != "PERSON":
                per_block[bidx].append(c)  # Presidio's structured recognisers act as independent evidence

    t0 = time.time()
    people = detect_people(nblocks, ner, email_cands)
    res.timings["names"] = time.time() - t0
    res.person_registry = people.registry
    res.stats.update({f"names_{k}": v for k, v in people.stats.items()})
    for bidx, cs in people.cands.items():
        per_block[bidx].extend(cs)

    t0 = time.time()
    for nb in nblocks:
        block = doc.blocks[nb.idx]
        nt = norms[nb.idx]
        fused = fuse(per_block.get(nb.idx, []))
        for c in fused:
            seg = nb.text[c.start:c.end]
            lead = len(seg) - len(seg.lstrip(" \t\r\n.,;:"))
            trail = len(seg) - len(seg.rstrip(" \t\r\n,;:" + ("" if c.type in ("ADDRESS", "PERSON") and seg.rstrip().endswith(".") and len(seg.split()[-1]) <= 2 else ".")))
            if lead or trail:
                c.start, c.end = c.start + lead, c.end - trail
                seg = nb.text[c.start:c.end]
            if c.type == "PHONE" and re.match(r"(?:19|20)\d\d[\-/ ]\d{2,3}[ .]\d", seg):
                continue  # '2026-041 13.1' is a section/reference number, not a telephone number
            if c.type == "PHONE":
                if seg.startswith("(") and ")" not in seg:
                    c.start += 1
                if seg.endswith(")") and "(" not in seg:
                    c.end -= 1
                seg = nb.text[c.start:c.end]
            if c.end <= c.start:
                continue
            if c.type == "PERSON" and _is_allowlisted(seg):
                continue
            if c.type in ("ADDRESS",) and any(seg.lower().startswith(a.lower()) for a in allowlist().get("corporate_addresses", [])):
                continue
            if c.conf < settings.review_band:
                continue
            os_, oe = nt.span_to_orig(c.start, c.end)
            rf = RawFinding(block=block, type=c.type, start=os_, end=oe, confidence=round(c.conf, 3),
                            detectors=sorted({d for d in c.detector.split("+")}), key=c.key,
                            ocr_derived=(block.source == "ocr"), note="")
            if c.conf >= settings.mask_threshold:
                res.findings.append(rf)
            else:
                res.review_candidates.append(rf)
    res.timings["fusion"] = time.time() - t0
    res.stats["findings"] = len(res.findings)
    res.stats["review_candidates"] = len(res.review_candidates)
    return res
