"""Document confidentiality label from what was found (types, distinct values) plus explicit markings. No raw values."""

from __future__ import annotations

import re
from collections import Counter

from .models import PipelineResult

_WEIGHT = {"SSN": 5, "PASSPORT": 5, "TAX_ID": 5, "FINANCIAL_ACCOUNT": 5, "DATE_OF_BIRTH": 4, "ADDRESS": 3, "EMPLOYEE_ID": 3,
           "PHONE": 1.5, "EMAIL": 1.5, "IP_ADDRESS": 1, "PERSON": 1}
_RESTRICTED_TYPES = {"SSN", "PASSPORT", "TAX_ID", "FINANCIAL_ACCOUNT", "DATE_OF_BIRTH"}
_MARK = [("RESTRICTED", re.compile(r"\b(strictly confidential|restricted|secret|highly confidential)\b", re.I)),
         ("CONFIDENTIAL", re.compile(r"\b(confidential|proprietary|do not (distribute|share)|nda)\b", re.I)),
         ("INTERNAL", re.compile(r"\b(internal use( only)?|internal only)\b", re.I))]
_ORDER = ["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"]


def classify(result: PipelineResult) -> dict:
    distinct = {(f.type, f.fingerprint) for f in result.findings}
    types = Counter(t for t, _ in distinct)
    score = round(sum(_WEIGHT.get(t, 1) * n for t, n in types.items()), 1)
    level, why = "PUBLIC", []
    def bump(to: str, reason: str) -> None:
        nonlocal level
        why.append(reason)
        if _ORDER.index(to) > _ORDER.index(level):
            level = to
    if result.document:
        marks = {m for b in result.document.blocks for m, rx in _MARK if rx.search(b.text)}
        for m, _ in _MARK:
            if m in marks:
                bump(m, f"document carries a {m.lower()} marking")
    if types:
        bump("INTERNAL", f"{sum(types.values())} distinct personal value(s)")
    if score >= 10:
        bump("CONFIDENTIAL", f"exposure score {score} >= 10")
    hi = sorted(set(types) & _RESTRICTED_TYPES)
    if hi:
        bump("RESTRICTED", "high-sensitivity identifiers: " + ", ".join(hi))
    return {"label": level, "score": score, "distinct_by_type": dict(types), "reasons": why}
