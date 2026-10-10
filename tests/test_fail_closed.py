"""The release gate: nothing reaches an LLM unless it is PASS, or REVIEW with a named approver."""

from __future__ import annotations

import ast
import time
from pathlib import Path

import pytest

import pii_shield.pipeline as pl
from pii_shield import process_bytes
from pii_shield.errors import BlockedError
from pii_shield.models import PipelineResult, SanitizedText, Status
from pii_shield.pipeline import Pipeline, release

from .conftest import FAST, make_doc, run_blocks
from .fixtures import SYN_VALUES, docx_bytes


def test_blocked_never_releases() -> None:
    r = process_bytes(b"", "a.pdf", FAST)
    with pytest.raises(BlockedError):
        release(r)
    with pytest.raises(BlockedError):
        release(r, approved_by="reviewer")  # even a human cannot release BLOCKED


def test_review_needs_named_approver() -> None:
    r = run_blocks(["Plain text with no personal data at all."])
    r.status = Status.REVIEW
    with pytest.raises(BlockedError):
        release(r)
    s = release(r, approved_by="reviewer-1")
    assert isinstance(s, SanitizedText) and s.approved_by == "reviewer-1"


def test_pass_releases_sanitized_only() -> None:
    r = run_blocks(["Escalate to o.brennagh@example.test today."])
    assert r.status == Status.PASS, r.reasons
    s = release(r)
    assert "@example.test" not in s.to_text() and "[EMAIL_1]" in s.to_text()


def test_sanitized_text_is_immutable() -> None:
    r = run_blocks(["nothing here"])
    s = release(r)
    with pytest.raises(Exception):
        s.document = "other"  # type: ignore[misc]


def test_unexpected_exception_blocks_without_leaking(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a, **k):
        raise ValueError("secret value Ottilie Brennagh 900-55-1234")

    monkeypatch.setattr(pl, "detect_document", boom)
    r = process_bytes(docx_bytes(), "a.docx", FAST)
    assert r.status == Status.BLOCKED
    assert r.reasons == ["INTERNAL_ERROR: ValueError"]
    assert not r.sanitized_blocks


def test_empty_extraction_blocks() -> None:
    r = run_blocks(["   ", "\n"])
    assert r.status == Status.BLOCKED
    assert any("EMPTY_EXTRACTION" in x for x in r.reasons)


def test_low_ocr_confidence_forces_review() -> None:
    doc = make_doc(["Quarterly summary without identifiers."], source="ocr")
    doc.stats.low_confidence_pages = [1]
    res = PipelineResult(status=Status.BLOCKED, document=doc)
    r = Pipeline(FAST)._process(doc, res, {}, time.time())
    assert r.status == Status.REVIEW and any("LOW_OCR_CONFIDENCE" in x for x in r.reasons)


def test_incomplete_ocr_forces_review() -> None:
    doc = make_doc(["Quarterly summary without identifiers."], source="ocr")
    doc.stats.ink_coverage = {1: 0.2}
    res = PipelineResult(status=Status.BLOCKED, document=doc)
    r = Pipeline(FAST)._process(doc, res, {}, time.time())
    assert r.status == Status.REVIEW and any("OCR_COMPLETENESS" in x for x in r.reasons)


def test_verifier_catches_detector_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate a detector blind spot: the verifier must force-redact and hold the document for review."""
    import pii_shield.detection.engine as eng

    monkeypatch.setattr(eng, "run_patterns", lambda t: [])
    r = run_blocks(["Customer SSN 900-55-1234 on file."])
    assert "900-55-1234" not in "\n".join(b.text for b in r.sanitized_blocks)
    assert r.status in (Status.REVIEW, Status.BLOCKED)
    assert r.notes["forced_redactions"] >= 1


def test_verifier_does_not_import_detection() -> None:
    src = Path(pl.__file__).parent / "verification" / "verifier.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    mods = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    mods += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    assert not any("detection" in m for m in mods), mods


def test_all_synthetic_values_masked() -> None:
    from .fixtures import SYN_TEXT

    out = "\n".join(b.text for b in run_blocks(SYN_TEXT).sanitized_blocks)
    for v in SYN_VALUES:
        assert v not in out, f"value of length {len(v)} survived"


def test_eval_reports_blocked_document_without_crashing() -> None:
    from pii_shield.eval import evaluate_result

    m = evaluate_result(process_bytes(b"", "a.pdf", FAST), [{"type": "EMAIL", "value": "a.b@example.test"}])
    assert m["status"] == "BLOCKED" and m["recall"] is None and m["leaked_values_in_sanitised_text"] == 0
