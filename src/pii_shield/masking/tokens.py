"""Stable-token masking. The same entity always becomes the same token inside one document
([PERSON_1] ... [PERSON_1]), so an LLM keeps the relationships without ever seeing the value.

There is NO reversible vault: tokens are sequential per document, and the audit fingerprint is a keyed HMAC."""

from __future__ import annotations

import hashlib
import hmac
import os
import re

from ..detection.engine import RawFinding
from ..models import Block, Finding, SanitizedBlock

_RUN_KEY = os.urandom(32)


def get_hmac_key() -> bytes:
    env = os.environ.get("PII_SHIELD_KEY")
    return env.encode() if env else _RUN_KEY


def entity_key(rf: RawFinding, text: str) -> str:
    t = rf.type
    if t == "PERSON":
        return rf.key or re.sub(r"[^a-z]", "", text.lower())
    if t == "EMAIL":
        return re.sub(r"\s+", "", text.lower())
    if t in ("PHONE", "SSN", "FINANCIAL_ACCOUNT"):
        d = re.sub(r"\D", "", text)
        return d or text.lower()
    if t == "DATE_OF_BIRTH":
        return re.sub(r"\s+", " ", text.lower())
    return re.sub(r"[^A-Za-z0-9]", "", text).upper()


def fingerprint(typ: str, key: str, hkey: bytes) -> str:
    return hmac.new(hkey, f"{typ}|{key}".encode(), hashlib.sha256).hexdigest()[:12]


def apply_masking(blocks: list[Block], raw: list[RawFinding], hkey: bytes | None = None) -> tuple[list[Finding], list[SanitizedBlock]]:
    hkey = hkey or get_hmac_key()
    order = {b.id: i for i, b in enumerate(blocks)}
    by_block: dict[str, list[RawFinding]] = {}
    for rf in raw:
        by_block.setdefault(rf.block.id, []).append(rf)

    # resolve overlaps in ORIGINAL offsets (normalisation can create rare edge overlaps): keep strongest
    kept_by_block: dict[str, list[RawFinding]] = {}
    for bid, items in by_block.items():
        items.sort(key=lambda r: (r.start, -r.confidence, -(r.end - r.start)))
        kept: list[RawFinding] = []
        for r in items:
            if kept and r.start < kept[-1].end:
                if r.confidence > kept[-1].confidence:
                    kept[-1] = r
                continue
            kept.append(r)
        kept_by_block[bid] = kept

    counters: dict[str, int] = {}
    token_of: dict[tuple[str, str], str] = {}
    findings: list[Finding] = []
    fid = 0
    # number tokens in document order
    for b in blocks:
        for r in kept_by_block.get(b.id, []):
            text = b.text[r.start:r.end]
            k = entity_key(r, text)
            tk = (r.type, k)
            if tk not in token_of:
                counters[r.type] = counters.get(r.type, 0) + 1
                token_of[tk] = f"[{r.type}_{counters[r.type]}]"
            fid += 1
            findings.append(
                Finding(
                    id=f"F{fid:05d}", type=r.type, block_id=b.id, start=r.start, end=r.end,
                    confidence=r.confidence, detectors=r.detectors, locator=b.locator, token=token_of[tk],
                    fingerprint=fingerprint(r.type, k, hkey), length=r.end - r.start, ocr_derived=r.ocr_derived, note=r.note,
                )
            )
    sanitized: list[SanitizedBlock] = []
    fmap: dict[str, list[Finding]] = {}
    for f in findings:
        fmap.setdefault(f.block_id, []).append(f)
    for b in blocks:
        text = b.text
        for f in sorted(fmap.get(b.id, []), key=lambda f: -f.start):
            text = text[:f.start] + f.token + text[f.end:]
        sanitized.append(SanitizedBlock(id=b.id, locator=b.locator, text=text))
    return findings, sanitized


def sanitized_to_original(block_findings: list[Finding], s: int, e: int) -> tuple[int, int] | None:
    """Map a span in the SANITISED text of one block back to the original text. None if it touches a token."""
    delta = 0
    for f in sorted(block_findings, key=lambda f: f.start):
        san_start = f.start + delta
        san_end = san_start + len(f.token)
        if s < san_end and e > san_start:
            return None
        if san_end <= s:
            delta += len(f.token) - (f.end - f.start)
    return s - delta, e - delta
