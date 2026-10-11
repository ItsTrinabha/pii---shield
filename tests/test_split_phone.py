"""Regression: phone numbers whose prefix and continuation are separated by OCR layout (eval 2026-10-11, PDF p.4/p.10).

Two shapes were seen on the scanned policy PDF:
  * same block, a neighbouring table cell interleaved on the prefix line: "+44 20 <name>\\n7555 0171"
  * prefix at the end of one OCR paragraph, continuation at the start of the next one on the same page.
The verifier missed the second shape entirely (it checked one block at a time). All values are synthetic.
"""

from __future__ import annotations

import re

import pytest

from pii_shield.detection.patterns import detect_phone, split_phone_pair
from pii_shield.eval.metrics import leaked_values
from pii_shield.masking.tokens import sanitized_to_original_parts
from pii_shield.models import Finding, Locator, SanitizedBlock
from pii_shield.verification import verify

from .conftest import run_blocks, sanitized

INTERLEAVED = [
    "Asset Management d.whitfield@example.test, +44 20 Lena Okafor\n7555 0171\nConsumer Banking",
    "Group Functions m.ostrova@example.test, +33 1 Tomas Brandt\n5555 0144",
    "Operations k.lind@example.test, +1 (212) Priya Raman\n555-0147\nnext row",
    "Vendor desk q.hale@example.test, +1 (704) VND-ABC-123\n555-0166",  # interleaved cell is an ID with digits (p.13)
    "Treasury x.cole@example.test, +1 (212) Treasury —\n555-0147 03/14/2026",  # a date follows the tail (p.25)
]
CROSS_BLOCK = [
    ("Consumer Banking d.whitfield@example.test, +1 (212)", "555-0147\nGroup Functions"),
    ("Technology k.lind@example.test, +46 8", "5555 0121\nAsset Management"),
    ("Markets |.ostrova@example.test, +49 69 Ola Berg", "5555 0177"),
]
NOT_PHONES = [
    "Spread widened +12 bps\n2025 2026 targets",
    "Q3 +20% growth\n2025 2026",
    "Score +3 (est)\nsee table 4",
    "Delta +2 (5) at 14 days\n1234 5678",  # a standalone number between head and line end: not a wrapped phone
    "+44 20 7555 0171\n2026 review cycle",  # complete number: next line must not be pulled in
]


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def _tail(text: str) -> str:
    """The continuation: digit groups at the start of the second line (a trailing date is not part of it)."""
    return re.match(r"\d[\d \-]*\d{4}", text.split("\n")[1]).group(0)  # type: ignore[union-attr]


def _covered(text: str, spans: list[tuple[int, int]], needle: str) -> bool:
    i = text.index(needle)
    return any(s <= i and i + len(needle) <= e for s, e in spans)


# ---------------------------------------------------------------- detector
@pytest.mark.parametrize("text", INTERLEAVED)
def test_detector_masks_prefix_and_continuation(text: str) -> None:
    spans = [(c.start, c.end) for c in detect_phone(text)]
    head = re.search(r"\+\d+ \(?\d+\)?", text).group(0)  # type: ignore[union-attr]
    tail = _tail(text)
    assert _covered(text, spans, head), "prefix not masked"
    assert _covered(text, spans, tail), "continuation not masked"
    name = text.split(head)[1].split("\n")[0].strip()
    assert not any(s <= text.index(name) < e for s, e in spans), "interleaved text must not be swallowed as PHONE"


@pytest.mark.parametrize("a,b", CROSS_BLOCK)
def test_split_pair_finds_both_halves(a: str, b: str) -> None:
    pair = split_phone_pair(a, b)
    assert pair is not None
    (hs, he), (ts, te) = pair
    assert a[hs:he].startswith("+") and _digits(b[ts:te]) == _digits(b.split("\n")[0])
    assert 8 <= len(_digits(a[hs:he] + b[ts:te])) <= 15


@pytest.mark.parametrize("text", NOT_PHONES)
def test_no_false_split(text: str) -> None:
    lines = text.split("\n")
    assert split_phone_pair(lines[0], lines[1]) is None
    assert all("\n" not in text[c.start:c.end] for c in detect_phone(text))
    assert not any(c.start >= len(lines[0]) for c in detect_phone(text)), "second line must not be tagged"


# ---------------------------------------------------------------- pipeline (detect -> mask -> verify -> gate)
@pytest.mark.parametrize("text", INTERLEAVED)
def test_pipeline_interleaved(text: str) -> None:
    res = run_blocks([text])
    out = sanitized(res)
    assert _digits(_tail(text))[-4:] not in out
    assert not re.search(r"\+\d", out), "country-code prefix is still readable"
    assert res.status.value != "BLOCKED", res.reasons
    toks = re.findall(r"\[PHONE_\d+\]", out)
    assert len(toks) == 2 and len(set(toks)) == 1, "both halves of one number share one stable token"


@pytest.mark.parametrize("a,b", CROSS_BLOCK)
def test_pipeline_cross_block(a: str, b: str) -> None:
    res = run_blocks([a, b])
    out = sanitized(res)
    assert _digits(b.split("\n")[0])[-4:] not in out, "continuation in the next block is still readable"
    assert not re.search(r"\+\d", out), "country-code prefix is still readable"
    assert res.status.value != "BLOCKED", res.reasons


# ---------------------------------------------------------------- independent verifier
def _sb(i: int, text: str, page: int = 1) -> SanitizedBlock:
    return SanitizedBlock(id=f"b{i}", locator=Locator(file="x.pdf", unit="page", index=page, block_id=f"b{i}"), text=text)


@pytest.mark.parametrize("a,b", CROSS_BLOCK)
def test_verifier_flags_cross_block_residual(a: str, b: str) -> None:
    a = a.replace("Ola Berg", "[PERSON_1]")  # the verifier sees sanitised text: an interleaved name is already a token
    v = verify([_sb(0, a), _sb(1, b)])
    hit_blocks = {h.block_id for h in v.hard_hits if h.rule.startswith("residual-phone")}
    assert hit_blocks == {"b0", "b1"}, "both halves must be flagged so the heal loop can redact both"


def test_verifier_does_not_join_across_pages() -> None:
    v = verify([_sb(0, "Total +12", page=1), _sb(1, "2025 2026 targets", page=2)])
    assert not v.hard_hits


def test_verifier_flags_interleaved_token() -> None:
    v = verify([_sb(0, "x [EMAIL_1], +44 20 [PERSON_3]\n7555 0171")])
    assert any(h.rule == "residual-phone-intl" for h in v.hard_hits)


# ---------------------------------------------------------------- heal loop mapping
def _f(start: int, end: int, token: str) -> Finding:
    loc = Locator(file="x.pdf", unit="page", index=1, block_id="b0")
    return Finding(id="F1", type="PERSON", block_id="b0", start=start, end=end, confidence=0.9, detectors=["t"], locator=loc,
                   token=token, fingerprint="0", length=end - start)


def test_hit_straddling_a_token_maps_to_the_parts_around_it() -> None:
    orig = "x, +44 20 Lena Okafor\n7555 0171"
    f = _f(orig.index("Lena"), orig.index("Okafor") + len("Okafor"), "[PERSON_1]")
    san = orig[:f.start] + f.token + orig[f.end:]
    s = san.index("+44")
    parts = sanitized_to_original_parts([f], s, len(san))
    assert [orig[a:b].strip() for a, b in parts] == ["+44 20", "7555 0171"]


# ---------------------------------------------------------------- metric
def test_leak_metric_sees_values_split_by_a_token() -> None:
    truth = [{"type": "PHONE", "value": "+44 20 7555 0171"}, {"type": "PHONE", "value": "+1 (212) 555-0147"}]
    san = "x [EMAIL_1], +44 20 [PERSON_3]\n7555 0171\ny [PHONE_2]"
    assert leaked_values(san, truth) == [0]


def test_split_halves_count_as_true_positives() -> None:
    from pii_shield.eval.metrics import evaluate_result

    res = run_blocks(["Asset Management d.whitfield@example.test, +44 20 Lena Okafor\n7555 0171"])
    truth = [{"type": "PHONE", "value": "+44 20 7555 0171"}, {"type": "EMAIL", "value": "d.whitfield@example.test"}]
    m = evaluate_result(res, truth)
    assert not [f for f in m["false_positives"] if f["type"] == "PHONE"]
    assert m["leaked_values_in_sanitised_text"] == 0


# ---------------------------------------------------------------- verifier: short international prefix (PDF p.13)
@pytest.mark.parametrize("text", ["k.lind@example.test, +44 20755 ABC-DEF-123", "call +1 (704) later", "desk +46 8 5"])
def test_verifier_flags_short_intl_prefix(text: str) -> None:
    assert any(h.rule.startswith("residual-phone") for h in verify([_sb(0, text)]).hard_hits)


@pytest.mark.parametrize("text", ["Spread +12 bps", "Q3 +20% growth", "Score +3 (est)", "Rated +1 overall", "x +2025"])
def test_verifier_ignores_non_phone_plus(text: str) -> None:
    assert not [h for h in verify([_sb(0, text)]).hard_hits if h.rule.startswith("residual-phone")]


def test_pipeline_redacts_short_intl_prefix() -> None:
    res = run_blocks(["Ops k.lind@example.test, +44 20755 ABC-DEF-123\n50171"])
    out = sanitized(res)
    assert "20755" not in out and not re.search(r"\+\d", out)
    assert res.status.value == "REVIEW", res.reasons
