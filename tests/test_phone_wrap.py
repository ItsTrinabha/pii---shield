"""Regression: phone numbers split across lines by OCR / table cells (open bug from STATUS.md)."""

from __future__ import annotations

import re

import pytest

from pii_shield.detection.patterns import detect_phone
from pii_shield.models import Locator, SanitizedBlock
from pii_shield.verification import verify

from .conftest import run_blocks, sanitized

WRAPPED = [
    "Contact: +1 (704)\n555-0166 for escalation",
    "Stockholm desk +46 8\n5555 0121",
    "Frankfurt desk +49 69\n5555 0177 (weekdays)",
    "US office (212)\n555-0147",
]


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


@pytest.mark.parametrize("text", WRAPPED)
def test_detector_covers_both_lines(text: str) -> None:
    cands = detect_phone(text)
    assert cands, "wrapped phone not detected"
    best = max(cands, key=lambda c: c.end - c.start)
    span = text[best.start:best.end]
    assert "\n" in span, "span must cross the line break so the tail is masked too"
    assert len(_digits(span)) >= 10


def test_complete_number_not_merged_with_next_line() -> None:
    text = "+44 20 7555 0171\n2026 review cycle"
    cands = detect_phone(text)
    assert cands
    assert all("\n" not in text[c.start:c.end] for c in cands)


@pytest.mark.parametrize("text", WRAPPED)
def test_verifier_flags_wrapped_residual(text: str) -> None:
    b = SanitizedBlock(id="b0", locator=Locator(file="x.pdf", unit="page", index=1, block_id="b0"), text=text)
    v = verify([b])
    assert any(h.rule.startswith("residual-phone") for h in v.hard_hits)


@pytest.mark.parametrize("text", WRAPPED)
def test_pipeline_leaves_no_phone_digits(text: str) -> None:
    res = run_blocks([text])
    out = sanitized(res)
    assert "[PHONE_1]" in out
    tail = _digits(text)[-4:]
    assert tail not in out, "last group of the number is still readable"
    assert res.status.value != "BLOCKED"
