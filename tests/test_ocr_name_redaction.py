"""SOFT name hits in OCR-derived blocks are auto-redacted (decision 2026-10-11, DOCX image12.png leak).

Rules: only blocks whose source is OCR; native-text SOFT hits are never auto-redacted; UI labels and business words are
not redacted; status stays REVIEW; the redactions are counted as forced, not as detections. All values are synthetic.
"""

from __future__ import annotations

from pii_shield.reporting.audit import audit_dict

from .conftest import run_blocks, sanitized

# OCR noise from a UI screenshot: the detector does not recognise the name, the verifier's gazetteer bigram does.
NOISE = "ulk import Cadence x\nfrapenecrmas Dana Okafor-Bell KC x\nind branding"
NAME = "Okafor-Bell"
REASON = "OCR-noise name candidates auto-redacted"


def _soft_name_hits(res) -> list:
    return [h for h in res.verification.soft_hits if h.rule in ("possible-unmasked-name", "name-fragment-next-to-token")]


def test_precondition_detector_misses_the_noise_name() -> None:
    res = run_blocks([NOISE], source="native")
    assert NAME in sanitized(res), "fixture no longer exercises the verifier path; pick a name the detector misses"
    assert _soft_name_hits(res)


def test_ocr_noise_name_is_redacted() -> None:
    res = run_blocks([NOISE], source="ocr")
    out = sanitized(res)
    assert NAME not in out and "Dana" not in out
    assert res.status.value == "REVIEW", res.reasons
    assert any(REASON in r and r.split(":", 1)[1].strip().startswith("1 ") for r in res.reasons), res.reasons
    forced = [f for f in res.findings if "verifier:forced" in f.detectors]
    assert forced and all(f.type == "PERSON" for f in forced)
    assert not _soft_name_hits(res)


def test_native_soft_hit_is_not_redacted() -> None:
    res = run_blocks([NOISE], source="native")
    assert NAME in sanitized(res)
    assert res.status.value == "REVIEW"
    assert not any(REASON in r for r in res.reasons)
    assert not any("verifier:forced" in f.detectors for f in res.findings)


def test_ui_label_is_not_redacted() -> None:
    res = run_blocks(["Mark Read  Archive\nReply  Forward"], source="ocr")
    assert "Mark Read" in sanitized(res)
    assert _soft_name_hits(res), "the verifier must still flag it for a human; only the auto-redaction skips it"
    assert not any(REASON in r for r in res.reasons)


def test_counted_as_forced_in_audit() -> None:
    res = run_blocks([NOISE], source="ocr")
    exp = audit_dict(res, include_time=False)["exposure"]
    assert exp["forced_ocr_name_candidates"] == 1
    assert exp["forced_by_verifier"] >= 1
    assert res.notes["forced_ocr_names"] == 1
