"""Independent verifier.

DESIGN RULE: this module must not import anything from pii_shield.detection. If the verifier reused the detector's
logic it would repeat the detector's blind spots. It therefore uses its own, deliberately over-sensitive heuristics
and a separate name gazetteer. A HARD hit means residual PII is almost certain; a SOFT hit means a human should look.
"""

from __future__ import annotations

import importlib
import pkgutil
import re
from collections.abc import Iterable
from functools import lru_cache

from ..models import SanitizedBlock, Verification, VerificationHit

_TOKEN_RX = re.compile(r"\[[A-Z_]+_\d+\]")

_EMAIL = re.compile(r"[\w.+\-]+\s?@\s?[\w\-]+\.[\w.\-]*\w")
_SSN = re.compile(r"(?<!\d)\d{3}[ \-–]\d{2}[ \-–]\d{4}(?!\d)")
_PHONE_A = re.compile(r"(?<![\w\d])\+\d[\d ().\-]{7,}\d")
_PHONE_B = re.compile(r"\(\d{3}\)[ ]?\d{3}[\- ]\d{4}|(?<!\d)\d{3}[.\-]\d{3}[.\-]\d{4}(?!\d)")
_DIGITRUN = re.compile(r"(?<![\w\-/.])\d(?:[ \-.]?\d){8,}(?![\w])")
_REFLIKE = re.compile(r"^(?:19|20)\d\d[\-/ ]\d{2,4}(?:[ \-]\d{1,3})?$")  # 2026-0417 1: a reference/date, not a number
_DATEISH = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_EMPID = re.compile(r"(?<![A-Za-z0-9])(?:EMP|DIR)[ ]?[\-–][ ]?[0-9OIlS]{3,}")
_PAN = re.compile(r"(?<![A-Za-z0-9])[A-Z]{5}\d{4}[A-Z](?![A-Za-z0-9])")
_PASSPORT = re.compile(r"(?i)passport\W{0,12}[A-Z]{0,2}\d{5,}")
_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\b"
_DOB = re.compile(rf"(?:(?i:\bDOB\b|date of birth|born(?: on)?))\W{{0,12}}(?:\d|{_MONTH})")
_STREET = re.compile(
    r"\b\d{1,5}[A-Za-z]?\s+(?:[A-Z][\w'’.\-]*\s+){1,4}(?:Street|St|Avenue|Ave|Road|Rd|Lane|Ln|Drive|Dr|Crescent|Boulevard|Blvd|Court|Ct|Way|Place|Pl|Terrace)\b"
)
_GENERIC_ID = re.compile(r"(?<![A-Za-z0-9\[])[A-Z]{2,4}-\d{4,6}(?![A-Za-z0-9\]])")
_BIGRAM = re.compile(r"\b([A-Z][a-z]{2,})\s+([A-Z][a-z'’]{2,}(?:-[A-Z][a-z]+)?)\b")
_NAME_MIDINIT = re.compile(r"\b([A-Z][a-z]{2,})[ \t]+[A-Z]\.[ \t]+([A-Z][a-z]{3,}(?:-[A-Z][a-z]+)?)\b")
_NEAR_TOKEN_A = re.compile(r"\[PERSON_\d+\][ \t]+([A-Z][a-z]{2,}(?:-[A-Z][a-z]+)?)\b")
_NEAR_TOKEN_B = re.compile(r"\b([A-Z][a-z]{2,})[ \t]+\[PERSON_\d+\]")

_SAFE_ID_PREFIX = {"INC", "LOS", "GRP", "OP", "RS", "RCSA", "KRI", "CD", "DDQ", "RSK", "ISS", "CTL", "SOP", "ISO", "NIST", "ACC",
                   "CHL", "SPK", "PH", "NY", "UK", "EU", "US", "PBR", "EXC", "BRC", "PLC", "TPR", "VND", "AUD", "REG", "CAS", "APP", "ASM", "TKT", "REQ"}
_YEAR_REF = re.compile(r"-(?:19|20)\d\d")
_COMMON = set(
    """group policy risk committee officer division management team review data board assurance compliance security operations
    finance legal audit framework process appetite control controls incident event loss credit market liquidity operational
    technology cyber third party conduct privacy protection regulatory reporting training workflow vendor vendors procurement
    quality approval approver owner owners user users chief head director vice president general counsel analytics engineering
    infrastructure cloud information enterprise strategy people culture client servicing payments shared services treasury
    financial planning internal external independent tier stage rule attribute questionnaire template version document
    appendix section table figure scale impact likelihood limit threshold indicator catalogue matrix responsible accountable
    consulted informed activity role holder programme model monitoring funding registration inventory intake case platform
    assessment exceptions emerging scenario stress testing change product ownership transparency consistency substance form
    forward focus second third line central local entity subsidiary regulator relationship deputy new high low medium critical
    severe major minor moderate elevated open closed status summary description details contact owner approved review next
    immediate treatment plan monthly quarterly annual weekly daily upon within where when this that these those with from
    inc ltd llc corp plc co company add create cancel another options option office peer reviewer reviewers please final
    submit save edit delete next back close search filter export import upload download settings home login logout
    onboarding offboarding renewal reassessment due diligence methodology configuration enhancement enhancements objectives
    outcomes approach final proposed current future key main primary secondary additional general specific standard custom
    street avenue road lane drive boulevard court place square floor suite tower building park plaza
    default required optional mandatory manual automatic automated trigger action actions notification notifications""".split()
)


@lru_cache(maxsize=1)
def _first_names() -> frozenset[str]:
    import faker.providers.person as pp

    out: set[str] = set()
    for m in pkgutil.iter_modules(pp.__path__):
        try:
            mod = importlib.import_module(f"faker.providers.person.{m.name}")
        except Exception:  # noqa: BLE001
            continue
        prov = getattr(mod, "Provider", None)
        for attr in dir(prov) if prov else []:
            if attr.startswith("first_names"):
                v = getattr(prov, attr)
                items = list(v.keys()) if isinstance(v, dict) else (list(v) if isinstance(v, (list, tuple)) else [])
                out.update(x.lower() for x in items if isinstance(x, str))
    return frozenset(out)


def _strip_tokens(text: str) -> str:
    """Blank out our own tokens (same length) so their digits are never read as PII."""
    return _TOKEN_RX.sub(lambda m: " " * len(m.group(0)), text)


def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


def verify(blocks: Iterable[SanitizedBlock], known_values: Iterable[str] = (), allow_substrings: Iterable[str] = (),
           strict: bool = False, allow_tokens: Iterable[str] = ()) -> Verification:
    """Scan SANITISED text. known_values are strings already identified as PII elsewhere in the document."""
    allow = [a.lower() for a in allow_substrings]
    allow_tok = {a.lower() for a in allow_tokens}
    hard: list[VerificationHit] = []
    soft: list[VerificationHit] = []
    gaz = _first_names()
    known = sorted({_norm_ws(v) for v in known_values if v and len(v.strip()) >= 4}, key=len, reverse=True)
    known_rx = re.compile(r"(?<![a-z0-9])(?:" + "|".join(re.escape(k) for k in known) + r")(?![a-z0-9])") if known else None

    def hit(sev: str, rule: str, b: SanitizedBlock, s: int, e: int) -> None:
        h = VerificationHit(severity=sev, rule=rule, block_id=b.id, locator=b.locator, start=s, end=e)
        (hard if sev == "HARD" else soft).append(h)

    for b in blocks:
        t = _strip_tokens(b.text)
        low = t.lower()
        for rule, rx in (("residual-email", _EMAIL), ("residual-ssn-shape", _SSN), ("residual-phone-intl", _PHONE_A),
                         ("residual-phone-local", _PHONE_B), ("residual-employee-id", _EMPID), ("residual-pan-shape", _PAN),
                         ("residual-passport", _PASSPORT), ("residual-dob-context", _DOB)):
            for m in rx.finditer(t):
                hit("HARD", rule, b, m.start(), m.end())
        for m in ([] if b.locator.unit in ("metadata", "hyperlink") else _DIGITRUN.finditer(t)):
            g = m.group(0).strip()
            if not _DATEISH.match(g) and not _REFLIKE.match(g):
                hit("HARD", "residual-long-digit-run", b, m.start(), m.end())
        for m in _STREET.finditer(t):
            if not any(m.group(0).lower().startswith(a) for a in allow):
                hit("HARD", "residual-street-address", b, m.start(), m.end())
        if known_rx:
            for m in known_rx.finditer(re.sub(r"\s", " ", low)):
                hit("HARD", "residual-known-value", b, m.start(), m.end())
        # ---- soft: things a human should glance at -------------------------------------------------------
        for m in _GENERIC_ID.finditer(t):
            if m.group(0).split("-")[0] not in _SAFE_ID_PREFIX and not _YEAR_REF.match(t[m.start() + len(m.group(0).split("-")[0]):m.start() + len(m.group(0).split("-")[0]) + 5]):
                hit("SOFT", "unclassified-identifier-shape", b, m.start(), m.end())
        for m in _BIGRAM.finditer(t):
            a, c = m.group(1).lower(), m.group(2).lower()
            if a in gaz and a not in _COMMON and c not in _COMMON and c.split("-")[0] not in _COMMON and a not in allow_tok and c not in allow_tok:
                hit("SOFT", "possible-unmasked-name", b, m.start(), m.end())
        for m in _NAME_MIDINIT.finditer(t):
            if m.group(1).lower() not in _COMMON and m.group(2).lower() not in _COMMON:
                hit("SOFT", "possible-unmasked-name", b, m.start(), m.end())
        for m in _NEAR_TOKEN_A.finditer(t):
            if m.group(1).lower() not in _COMMON:
                hit("SOFT", "name-fragment-next-to-token", b, m.start(1), m.end(1))
        for m in _NEAR_TOKEN_B.finditer(t):
            if m.group(1).lower() not in _COMMON:
                hit("SOFT", "name-fragment-next-to-token", b, m.start(1), m.end(1))

    passed = not hard and (not soft if strict else True)
    return Verification(passed=passed, hard_hits=hard, soft_hits=soft,
                        rules_run=["email", "ssn", "phone", "employee-id", "pan", "passport", "dob-context", "long-digit-run",
                                   "street-address", "known-value-residual", "identifier-shape", "unmasked-name", "name-fragment"])
