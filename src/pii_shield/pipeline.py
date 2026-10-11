"""The gateway: extract -> detect -> fuse -> mask -> verify -> (heal) -> release decision. Fails closed."""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from .detection import RawFinding, detect_document
from .detection.normalize import normalize
from .errors import BlockedError, PiiShieldError
from .extraction import extract
from .masking import apply_masking, get_hmac_key, sanitized_to_original_parts
from .models import (
    Block, ExtractedDocument, Finding, PipelineResult, SanitizedBlock, SanitizedText, Status, Verification, compute_seal,
)
from .settings import Settings, allowlist
from .verification import verify

log = logging.getLogger("pii_shield")  # NEVER log document text or PII values: types, counts, codes only

_RULE_TYPE = {
    "residual-email": "EMAIL", "residual-ssn-shape": "SSN", "residual-phone-intl": "PHONE", "residual-phone-local": "PHONE",
    "residual-employee-id": "EMPLOYEE_ID", "residual-pan-shape": "TAX_ID", "residual-passport": "PASSPORT",
    "residual-dob-context": "DATE_OF_BIRTH", "residual-street-address": "ADDRESS", "residual-long-digit-run": "UNCLASSIFIED",
}
_SOFT_NAME_RULES = ("possible-unmasked-name", "name-fragment-next-to-token")


class Pipeline:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()

    # ------------------------------------------------------------------------------------------------------
    def run(self, data: bytes, file_name: str) -> PipelineResult:
        st = self.settings
        t_all = time.time()
        timings: dict[str, float] = {}
        result = PipelineResult(status=Status.BLOCKED, config_digest=st.digest())
        try:
            t0 = time.time()
            doc = extract(data, file_name, st)
            timings["extract"] = round(time.time() - t0, 2)
            result.document = doc
            return self._process(doc, result, timings, t_all)
        except PiiShieldError as e:
            result.status = Status.BLOCKED
            result.reasons = [f"{e.code}: {e}"]
            log.warning("blocked file=%s code=%s", file_name[:80], e.code)
        except Exception as e:  # noqa: BLE001 - anything unexpected is also fail-closed, message carries no content
            result.status = Status.BLOCKED
            result.reasons = [f"INTERNAL_ERROR: {type(e).__name__}"]
            log.exception("unexpected failure (type only logged)")
        result.timings = timings
        return result

    # ------------------------------------------------------------------------------------------------------
    def _process(self, doc: ExtractedDocument, result: PipelineResult, timings: dict[str, float], t_all: float) -> PipelineResult:
        st = self.settings
        t0 = time.time()
        det = detect_document(doc, st)
        timings["detect"] = round(time.time() - t0, 2)
        timings.update({f"detect.{k}": round(v, 2) for k, v in det.timings.items()})
        result.notes["detector_stats"] = det.stats

        raw: list[RawFinding] = list(det.findings)
        t0 = time.time()
        findings, sanitized = apply_masking(doc.blocks, raw)
        timings["mask"] = round(time.time() - t0, 2)

        allow = allowlist().get("corporate_addresses", [])
        allow_tok = sorted({t for o in allowlist().get("organisations", []) for t in re.findall(r"[A-Za-z]+", o)})
        forced_total = 0
        ocr_names = 0
        verification: Verification | None = None
        for rnd in range(4):
            t0 = time.time()
            known = self._known_values(doc.blocks, findings)
            verification = verify(sanitized, known_values=known, allow_substrings=allow, strict=st.strict_verifier, allow_tokens=allow_tok)
            timings[f"verify.{rnd}"] = round(time.time() - t0, 2)
            if verification.hard_hits:
                new_raw = self._force_findings(doc, findings, verification)
                if not new_raw:
                    break  # cannot map the hit back to the source text -> stays a HARD hit -> BLOCKED
                forced_total += len(new_raw)
            else:
                # only once HARD hits are gone: SOFT name hits in OCR text (scans, screenshots) are redacted as well
                new_raw = self._force_ocr_names(doc, findings, verification)
                if not new_raw:
                    break
                ocr_names += len(new_raw)
            raw.extend(new_raw)
            findings, sanitized = apply_masking(doc.blocks, raw)
        else:
            known = self._known_values(doc.blocks, findings)
            verification = verify(sanitized, known_values=known, allow_substrings=allow, strict=st.strict_verifier, allow_tokens=allow_tok)

        reasons: list[str] = []
        status = Status.PASS
        assert verification is not None
        if verification.hard_hits:
            status = Status.BLOCKED
            reasons.append(f"VERIFIER_HARD_HITS: {len(verification.hard_hits)} residual PII signal(s) could not be removed")
        else:
            if forced_total:
                status = Status.REVIEW
                reasons.append(f"VERIFIER_FORCED_REDACTION: independent verifier found {forced_total} item(s) the detectors missed; "
                               f"they were redacted, a human should review this document")
            if ocr_names:
                status = Status.REVIEW
                reasons.append(f"OCR_NAME_REDACTION: {ocr_names} OCR-noise name candidates auto-redacted")
            if verification.soft_hits:
                status = Status.REVIEW if status != Status.BLOCKED else status
                if st.strict_verifier:
                    status = Status.BLOCKED
                reasons.append(f"VERIFIER_SOFT_HITS: {len(verification.soft_hits)} possible leftover(s) to review")
            if det.review_candidates:
                status = Status.REVIEW
                reasons.append(f"LOW_CONFIDENCE_CANDIDATES: {len(det.review_candidates)} candidate(s) below the masking threshold")
            s = doc.stats
            if s.low_confidence_pages:
                status = Status.REVIEW
                reasons.append(f"LOW_OCR_CONFIDENCE: pages {s.low_confidence_pages}")
            weak = [p for p, v in s.ink_coverage.items() if v < st.min_ink_coverage]
            if weak:
                status = Status.REVIEW
                reasons.append(f"OCR_COMPLETENESS: pages {weak} contain ink that OCR did not read")
            if s.unsupported_media:
                status = Status.REVIEW
                reasons.append(f"UNSUPPORTED_MEDIA: {len(s.unsupported_media)} embedded item(s) were not analysed")
            if not any(b.text.strip() for b in doc.blocks):
                status = Status.BLOCKED
                reasons.append("EMPTY_EXTRACTION: no text could be extracted")
        result.status = status
        result.reasons = reasons
        result.findings = findings
        result.sanitized_blocks = sanitized
        result.verification = verification
        result.notes["forced_redactions"] = forced_total + ocr_names  # forced, not detections
        result.notes["forced_ocr_names"] = ocr_names
        result.notes["review_candidates"] = [
            {"type": r.type, "block_id": r.block.id, "locator": r.block.locator.label(), "confidence": r.confidence,
             "start": r.start, "end": r.end} for r in det.review_candidates
        ]
        result.timings = {**timings, "total": round(time.time() - t_all, 2)}
        log.info("done file=%s status=%s findings=%d", doc.file_name[:60], status.value, len(findings))
        return result

    # ------------------------------------------------------------------------------------------------------
    @staticmethod
    def _known_values(blocks: list[Block], findings: list[Finding]) -> list[str]:
        by_id = {b.id: b for b in blocks}
        out: set[str] = set()
        for f in findings:
            v = by_id[f.block_id].text[f.start:f.end]
            v = re.sub(r"\s+", " ", v).strip()
            if f.type == "PERSON" and len(v) < 5:
                continue
            if len(v) >= 4:
                out.add(v)
        return sorted(out)

    @staticmethod
    def _force_findings(doc: ExtractedDocument, findings: list[Finding], ver: Verification) -> list[RawFinding]:
        """Turn verifier HARD hits into forced redactions (over-redaction is the safe failure mode)."""
        by_id = {b.id: b for b in doc.blocks}
        per_block: dict[str, list[Finding]] = {}
        for f in findings:
            per_block.setdefault(f.block_id, []).append(f)
        out: list[RawFinding] = []
        seen: set[tuple[str, int, int]] = set()
        known_types: dict[str, str] = {}
        for f in findings:
            known_types[re.sub(r"\s+", " ", by_id[f.block_id].text[f.start:f.end]).strip().lower()] = f.type
        for h in ver.hard_hits:
            b = by_id[h.block_id]
            # a hit that straddles existing tokens ('+44 20 [PERSON_3]\n7555 0171') is redacted piece by piece
            for s, e in sanitized_to_original_parts(per_block.get(b.id, []), h.start, h.end):
                seg = b.text[s:e]
                s, e = s + len(seg) - len(seg.lstrip()), e - (len(seg) - len(seg.rstrip()))
                if e <= s or e > len(b.text) or not any(ch.isalnum() for ch in b.text[s:e]) or (b.id, s, e) in seen:
                    continue
                seen.add((b.id, s, e))
                typ = _RULE_TYPE.get(h.rule)
                if h.rule == "residual-known-value":
                    typ = known_types.get(re.sub(r"\s+", " ", b.text[s:e]).strip().lower(), "UNCLASSIFIED")
                out.append(RawFinding(block=b, type=typ or "UNCLASSIFIED", start=s, end=e, confidence=0.9,
                                      detectors=["verifier:forced"], key="", ocr_derived=(b.source == "ocr"),
                                      note="found by independent verifier, missed by detectors"))
        return out

    @staticmethod
    def _force_ocr_names(doc: ExtractedDocument, findings: list[Finding], ver: Verification) -> list[RawFinding]:
        """SOFT name hits inside OCR-derived blocks become forced PERSON redactions. Native text is never touched (a human
        reviews it), and a hit containing a UI label or business word ('Mark Read', 'Forward Plan') is skipped."""
        by_id = {b.id: b for b in doc.blocks}
        per_block: dict[str, list[Finding]] = {}
        for f in findings:
            per_block.setdefault(f.block_id, []).append(f)
        al = allowlist()
        skip = {w.lower() for w in al.get("ui_labels", []) + al.get("business_vocabulary", [])}
        skip |= {t.lower() for o in al.get("organisations", []) for t in re.findall(r"[A-Za-z]+", o)}
        out: list[RawFinding] = []
        seen: set[tuple[str, int, int]] = set()
        for h in ver.soft_hits:
            b = by_id[h.block_id]
            if h.rule not in _SOFT_NAME_RULES or b.source != "ocr":
                continue
            for s, e in sanitized_to_original_parts(per_block.get(b.id, []), h.start, h.end):
                seg = b.text[s:e]
                s, e = s + len(seg) - len(seg.lstrip()), e - (len(seg) - len(seg.rstrip()))
                words = [w.lower() for w in re.findall(r"[A-Za-z]+", b.text[s:e])]
                if e <= s or not words or any(w in skip for w in words) or (b.id, s, e) in seen:
                    continue
                seen.add((b.id, s, e))
                out.append(RawFinding(block=b, type="PERSON", start=s, end=e, confidence=0.6, detectors=["verifier:forced"],
                                      key="", ocr_derived=True, note="OCR-noise name candidate (SOFT verifier hit), auto-redacted"))
        return out


# ---- convenience API ---------------------------------------------------------------------------------------

def process_bytes(data: bytes, file_name: str, settings: Settings | None = None) -> PipelineResult:
    return Pipeline(settings).run(data, file_name)


def process_path(path: str | Path, settings: Settings | None = None) -> PipelineResult:
    p = Path(path)
    return Pipeline(settings).run(p.read_bytes(), p.name)


def release(result: PipelineResult, approved_by: str | None = None) -> SanitizedText:
    """The ONLY way to obtain LLM-facing text. PASS releases automatically; REVIEW needs a named human approver;
    BLOCKED never releases."""
    if result.status == Status.BLOCKED:
        raise BlockedError("document is BLOCKED: " + "; ".join(result.reasons)[:300])
    if result.status == Status.REVIEW and not approved_by:
        raise BlockedError("document needs human review before release (REVIEW status)")
    assert result.document is not None
    blocks = tuple(result.sanitized_blocks)
    name = result.document.file_name
    return SanitizedText(document=name, blocks=blocks, approved_by=approved_by,
                         seal=compute_seal(name, blocks, approved_by))
