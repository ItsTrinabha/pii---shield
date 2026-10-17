"""Audit / exposure report. Contains NO raw PII: only types, locators, tokens, offsets, confidences, fingerprints."""

from __future__ import annotations

import html
import json
from collections import Counter
from datetime import datetime, timezone

from ..models import CLASSIFICATION, PipelineResult


def audit_dict(result: PipelineResult, include_time: bool = True) -> dict:
    doc = result.document
    by_type = Counter(f.type for f in result.findings)
    by_class: Counter[str] = Counter()
    for f in result.findings:
        by_class[CLASSIFICATION.get(f.type, ("Unclassified", ""))[0]] += 1
    distinct = {(f.type, f.fingerprint) for f in result.findings if f.fingerprint}
    ver = result.verification
    return {
        "report_version": 1,
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds") if include_time else None,
        "status": result.status.value,
        "safe_for_llm": result.safe_for_llm,
        "reasons": result.reasons,
        "document": {
            "name": doc.file_name if doc else None,
            "type": doc.file_type if doc else None,
            "sha256": doc.sha256 if doc else None,
            "size_bytes": doc.size_bytes if doc else None,
            "stats": doc.stats.model_dump() if doc else None,
            "warnings": doc.warnings if doc else [],
        },
        "confidentiality": result.notes.get("confidentiality"),
        "exposure": {
            "total_findings": len(result.findings),
            "distinct_values": len(distinct),
            "by_type": dict(by_type.most_common()),
            "by_classification": dict(by_class.most_common()),
            "ocr_derived_findings": sum(f.ocr_derived for f in result.findings),
            "forced_by_verifier": result.notes.get("forced_redactions", 0),
            "forced_ocr_name_candidates": result.notes.get("forced_ocr_names", 0),
        },
        "verification": {
            "passed": ver.passed if ver else None,
            "hard_hits": len(ver.hard_hits) if ver else None,
            "soft_hits": len(ver.soft_hits) if ver else None,
            "hard_rules": dict(Counter(h.rule for h in ver.hard_hits)) if ver else {},
            "soft_rules": dict(Counter(h.rule for h in ver.soft_hits)) if ver else {},
            "rules_run": ver.rules_run if ver else [],
        },
        "review_candidates": result.notes.get("review_candidates", []),
        "findings": [
            {
                "id": f.id, "type": f.type, "classification": CLASSIFICATION.get(f.type, ("", ""))[0],
                "token": f.token, "action": f.action, "confidence": f.confidence, "detectors": f.detectors,
                "locator": f.locator.label(), "block_id": f.block_id, "start": f.start, "end": f.end,
                "length": f.length, "fingerprint": f.fingerprint, "ocr_derived": f.ocr_derived,
            }
            for f in result.findings
        ],
        "timings_s": result.timings,
        "config_digest": result.config_digest,
    }


def audit_json(result: PipelineResult, **kw) -> str:
    return json.dumps(audit_dict(result, **kw), indent=2, ensure_ascii=False)


_COLOR = {"PASS": "#1a7f37", "REVIEW": "#9a6700", "BLOCKED": "#cf222e"}


def audit_html(result: PipelineResult) -> str:
    d = audit_dict(result)
    e = html.escape
    rows = "".join(
        f"<tr><td>{e(f['id'])}</td><td>{e(f['type'])}</td><td>{e(f['classification'])}</td><td>{e(f['token'])}</td>"
        f"<td>{e(f['locator'])}</td><td>{f['confidence']:.2f}</td><td>{e(', '.join(f['detectors']))}</td></tr>"
        for f in d["findings"]
    )
    types = "".join(f"<tr><td>{e(k)}</td><td>{v}</td></tr>" for k, v in d["exposure"]["by_type"].items())
    reasons = "".join(f"<li>{e(r)}</li>" for r in d["reasons"]) or "<li>none</li>"
    col = _COLOR.get(d["status"], "#444")
    return f"""<!doctype html><meta charset="utf-8"><title>Cloak audit - {e(str(d['document']['name']))}</title>
<style>body{{font:14px system-ui;margin:2rem;max-width:1100px}}table{{border-collapse:collapse;width:100%;margin:1rem 0}}
td,th{{border:1px solid #ccc;padding:4px 8px;text-align:left}}th{{background:#f4f4f4}}
.badge{{display:inline-block;padding:4px 14px;border-radius:12px;color:#fff;background:{col};font-weight:700}}</style>
<h1>Cloak exposure report</h1>
<p>File: <b>{e(str(d['document']['name']))}</b> &middot; sha256 <code>{e(str(d['document']['sha256']))[:16]}</code> &middot;
status <span class="badge">{e(d['status'])}</span></p>
<p>This report contains no raw PII values: only types, locations, tokens and keyed fingerprints.</p>
<h2>Why this status</h2><ul>{reasons}</ul>
<h2>Exposure by type</h2><table><tr><th>Type</th><th>Findings</th></tr>{types}</table>
<p>Total {d['exposure']['total_findings']} findings, {d['exposure']['distinct_values']} distinct values,
{d['exposure']['forced_by_verifier']} forced by the independent verifier
(of which {d['exposure']['forced_ocr_name_candidates']} OCR-noise name candidates).</p>
<h2>Verification</h2><p>Hard hits: {d['verification']['hard_hits']} &middot; soft hits: {d['verification']['soft_hits']}</p>
<h2>Findings</h2><table><tr><th>ID</th><th>Type</th><th>Class</th><th>Token</th><th>Location</th><th>Conf.</th><th>Detectors</th></tr>{rows}</table>
"""
