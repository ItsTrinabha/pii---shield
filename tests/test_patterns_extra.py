"""Extended regex rules (national IDs, more phones/financial/network, postcodes, vehicles, secrets).
Ported from the pii_regex_rules self-tests. All values are synthetic or published documentation examples."""

from __future__ import annotations

import pytest

from pii_shield.detection.normalize import normalize
from pii_shield.detection.patterns import run_patterns
from pii_shield.models import Locator, SanitizedBlock
from pii_shield.verification import verify

from .conftest import run_blocks, sanitized


def _hits(text: str) -> list[tuple[str, str, float]]:
    return [(c.type, c.detector, c.conf) for c in run_patterns(normalize(text).text)]


def _masked(text: str) -> set[str]:
    return {f.type for f in run_blocks([text]).findings}


# ---- positives: the value is found AND masked (confidence >= the mask threshold) -------------------------------------
@pytest.mark.parametrize("text,typ", [
    ("mail jane.doe+hr@example.co.uk now", "EMAIL"),
    ("write to jane.doe [at] example [dot] com", "EMAIL"),
    ("write to jane.doe at example dot com", "EMAIL"),
    ("call +44 20 7946 0958 today", "PHONE"),
    ("reach (415) 555-0132 or 415-555-0132", "PHONE"),
    ("mobile +91 98765 43210", "PHONE"),
    ("07700 900123", "PHONE"),
    ("Tel: +1 415 555 0132", "PHONE"),
    ("WhatsApp: 98765 43210", "PHONE"),
    ("server 192.168.10.25 failed", "IP_ADDRESS"),
    ("the gateway is 10.0.0.5.", "IP_ADDRESS"),  # sentence full stop after the address
    ("addr 2001:0db8:85a3:0000:0000:8a2e:0370:7334 up", "IP_ADDRESS"),
    ("addr fe80::1ff:fe23:4567:890a up", "IP_ADDRESS"),
    ("nic 00:1A:2B:3C:4D:5E ok", "TECH_ID"),
    ("ftp://admin:S3cr3tPass@10.0.0.5/data", "SECRET"),
    ("https://x.io/a?api_key=abcdef123456", "SECRET"),
    ("SSN 123-45-6789", "SSN"),
    ("SSN 900-55-2043", "SSN"),  # 9xx kept on purpose (ITIN range, synthetic SSNs)
    ("Aadhaar 2345 6789 0124", "GOV_ID"),
    ("PAN ABCPE1234F", "TAX_ID"),
    ("GST 22AAAAA0000A1Z5", "TAX_ID"),
    ("Passport No: N1234567", "PASSPORT"),
    ("vehicle MH12AB1234", "TECH_ID"),
    ("NI AB 12 34 56 C", "GOV_ID"),
    ("SIN 046 454 286", "GOV_ID"),
    ("home address London SW1A 1AA", "ADDRESS"),
    ("Austin, TX 78701", "ADDRESS"),
    ("Pincode: 632014", "ADDRESS"),
    ("card 4111 1111 1111 1111", "FINANCIAL_ACCOUNT"),
    ("IBAN GB82 WEST 1234 5698 7654 32", "FINANCIAL_ACCOUNT"),
    ("SWIFT DEUTDEFF500", "FINANCIAL_ACCOUNT"),
    ("IFSC SBIN0001234", "FINANCIAL_ACCOUNT"),
    ("routing 021000021", "FINANCIAL_ACCOUNT"),
    ("A/C No: 123456789012", "FINANCIAL_ACCOUNT"),
    ("send to 1BoatSLRHtKNngkdXEeobR76b53LETtpyT", "FINANCIAL_ACCOUNT"),
    ("0x52908400098527886E0F7030069857D2E4169EE7", "FINANCIAL_ACCOUNT"),
    ("DOB: 14/03/1999", "DATE_OF_BIRTH"),
    ("EMP-20417 approved", "EMPLOYEE_ID"),
    ("STF_204178 approved", "EMPLOYEE_ID"),
    ("Employee ID: E48213", "EMPLOYEE_ID"),
    ("VIN 1HGCM82633A004352", "TECH_ID"),
    ("AKIAIOSFODNN7EXAMPLE", "SECRET"),
    ("token ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8", "SECRET"),
    ("key AIza" + "SyA1234567890abcdefghijklmnopqrstuv", "SECRET"),
    ("xoxb-1234567890-abcdefghij", "SECRET"),
    ("sk_test_" + "4eC39HqLyjWDarjtT1zdp7dc", "SECRET"),
    ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r", "SECRET"),
    ("-----BEGIN RSA PRIVATE KEY-----", "SECRET"),
    ('password = "hunter2hunter2"', "SECRET"),
])
def test_masked(text: str, typ: str) -> None:
    assert typ in _masked(text)


# ---- negatives: the validator / gate rejects them ---------------------------------------------------------------------
@pytest.mark.parametrize("text,typ", [
    ("price@5 not mail", "EMAIL"),
    ("version 1.2.3 and 999.1.1.1 and 0.0.0.0 and 1.2.3.4.5", "IP_ADDRESS"),
    ("id 000-12-3456 and 666-12-3456 and 123-00-4567 and 123-45-0000", "SSN"),
    ("num 4111 1111 1111 1112", "FINANCIAL_ACCOUNT"),  # Luhn fails
    ("GB82 WEST 1234 5698 7654 33", "FINANCIAL_ACCOUNT"),  # mod-97 fails
    ("2345 6789 0125", "GOV_ID"),  # Verhoeff fails
    ("046 454 287", "GOV_ID"),  # SIN Luhn fails
    ("routing 021000022", "FINANCIAL_ACCOUNT"),  # ABA checksum fails
    ("BG 12 34 56 A", "GOV_ID"),  # invalid NINO prefix
    ("order 123-456-7890", "PHONE"),  # NANP area code cannot start with 1
    ("send to 1BoatSLRHtKNngkdXEeobR76b53LETtpyX", "FINANCIAL_ACCOUNT"),  # base58check fails
    ("Password: minimum twelve characters", "SECRET"),  # policy prose, not a credential
    ("password: ********", "SECRET"),  # placeholder
    ("Passport number process applies", "PASSPORT"),  # a word after 'passport', not a number
    ("ref 1HGCM82633A004352 in the register", "TECH_ID"),  # 17-char code without vehicle context
    ("OPERATIONAL RISK FRAMEWORK", "FINANCIAL_ACCOUNT"),  # SHOUTED heading is not a BIC
])
def test_detector_rejects(text: str, typ: str) -> None:
    # detector level: the independent verifier may still force-redact a checksum-failing shape (fail closed, REVIEW)
    assert typ not in {t for t, _, conf in _hits(text) if conf >= 0.45}


def test_verifier_backstops_rejected_shapes() -> None:
    res = run_blocks(["order 123-456-7890"])
    assert all(f.detectors == ["verifier:forced"] for f in res.findings) and res.status.value == "REVIEW"


# ---- gated shape-only rules: found, below the mask threshold, so the document goes to REVIEW instead -------------------
@pytest.mark.parametrize("text,typ", [
    ("code N1234567", "PASSPORT"),
    ("London SW1A 1AA", "ADDRESS"),
    ("ref TX 78701", "ADDRESS"),
    ("MH12AB1234", "TECH_ID"),
    ("value 046 454 286", "GOV_ID"),
])
def test_gated_goes_to_review(text: str, typ: str) -> None:
    res = run_blocks([text])
    assert typ not in {f.type for f in res.findings}
    assert typ in {c["type"] for c in res.notes["review_candidates"]}
    assert res.status.value == "REVIEW"


def test_stable_token_for_new_types() -> None:
    out = sanitized(run_blocks(["key AKIAIOSFODNN7EXAMPLE and again AKIAIOSFODNN7EXAMPLE, NI AB123456C"]))
    assert out.count("[SECRET_1]") == 2 and "[GOV_ID_1]" in out and "AKIA" not in out


@pytest.mark.parametrize("text,rule", [
    ("AKIAIOSFODNN7EXAMPLE", "residual-secret"),
    ("-----BEGIN PRIVATE KEY-----", "residual-secret"),
    ("NI AB 12 34 56 C", "residual-nino-shape"),
    ("22AAAAA0000A1Z5", "residual-gstin-shape"),
    ("00:1A:2B:3C:4D:5E", "residual-mac"),
    ("fe80::1ff:fe23:4567:890a", "residual-ipv6"),
    ("0x52908400098527886E0F7030069857D2E4169EE7", "residual-crypto-address"),
])
def test_verifier_flags_leftovers(text: str, rule: str) -> None:
    blk = SanitizedBlock(id="b", locator=Locator(file="x", unit="page", index=1), text=text)
    assert rule in {h.rule for h in verify([blk]).hard_hits}


@pytest.mark.parametrize("text", [
    "src 203.0.113.45 blocked", "the gateway is 203.0.113.45.", "host 203.0.113.45:8080", "range 203.0.113.0/24",
    "(203.0.113.45)", "padded 203.000.113.045", "login from 203. 0.113.45", "source IP 203,0.113.45",
    "server 2O3.0.1l3.45", "addr 2001:db8::8a2e:370:7334", "addr fe80::1", "host 8.8.8.8",
])
def test_ip_variants_fully_masked(text: str) -> None:
    out = sanitized(run_blocks([text]))
    assert "[IP_ADDRESS_1]" in out and not any(ch.isdigit() for ch in out.replace("[IP_ADDRESS_1]", "").replace("8080", "")
                                                                         .replace("/24", ""))


@pytest.mark.parametrize("text", ["steps 1. 2. 3. 4 follow", "see section 4.2.1.3", "version 10.2.3.4567", "loopback 127.0.0.1",
                                  "meeting 10:30:45"])
def test_ip_lookalikes_ignored(text: str) -> None:
    res = run_blocks([text])
    assert not res.findings and not res.verification.hard_hits


def test_ocr_ip_without_context_goes_to_review() -> None:
    res = run_blocks(["note 203. 0.113.45 here"])
    assert "IP_ADDRESS" in {c["type"] for c in res.notes["review_candidates"]} or res.status.value == "REVIEW"


def test_verifier_ignores_clock_time() -> None:
    blk = SanitizedBlock(id="b", locator=Locator(file="x", unit="page", index=1), text="meeting at 10:30:45 today")
    assert not verify([blk]).hard_hits


# ---- GENERIC_ID catch-all ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text", ["customer CUST-48213 called", "file HR/EMP/2291 opened", "record AB_X1_2024", "case CLM-77-A9-100234"])
def test_generic_id_masked(text: str) -> None:
    assert "GENERIC_ID" in _masked(text)


@pytest.mark.parametrize("text,typ", [("EMP-20417 approved", "EMPLOYEE_ID"), ("Aadhaar 2345-6789-0124", "GOV_ID")])
def test_specific_type_beats_generic_id(text: str, typ: str) -> None:
    found = _masked(text)
    assert typ in found and "GENERIC_ID" not in found


@pytest.mark.parametrize("text", ["ticket INC-2026-0417 closed", "loss LOS-2026-0088", "policy GRP-POL-001", "per ISO/27001",
                                  "control NIST-800", "ref RCSA-2025-014"])
def test_generic_id_skips_reference_prefixes(text: str) -> None:
    assert "GENERIC_ID" not in _masked(text)


def test_generic_id_stable_token() -> None:
    out = sanitized(run_blocks(["CUST-48213 and again CUST-48213, then CUST-55120"]))
    assert out.count("[GENERIC_ID_1]") == 2 and "[GENERIC_ID_2]" in out
