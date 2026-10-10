"""Value-based evaluation. Ground truth lists the PII VALUES that exist in a document (type + string), annotated
independently of detector output. Everything is computed on the extracted text, so extraction misses are reported
separately (a value the extractor never produced cannot be detected).

Definitions (occurrence level):
  * occurrence  = a place where a GT value appears in a block's text (whitespace/case-insensitive).
  * covered     = some finding overlaps that occurrence by >= 50% of the occurrence length.
  * recall(type)= covered / occurrences of GT values of that type (type-agnostic coverage reported as `leak`).
  * precision   = findings overlapping any GT occurrence / all findings; the rest are listed for adjudication.
  * leak        = GT occurrences NOT covered, and still present in the SANITISED text (the number that matters).
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

from ..models import PipelineResult


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - m) / d, (c + m) / d)


def load_truth(path: str | Path) -> list[dict]:
    return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]


def _ws(s: str) -> str:
    return re.sub(r"\s+", " ", s)


def _occurrences(text: str, value: str) -> list[tuple[int, int]]:
    """Find value in text tolerating arbitrary whitespace (incl. line wraps) between its words."""
    parts = [re.escape(p) for p in value.split()]
    if not parts:
        return []
    rx = re.compile(r"(?<![A-Za-z0-9])" + r"\s+".join(parts) + r"(?![A-Za-z0-9])", re.I)
    return [(m.start(), m.end()) for m in rx.finditer(text)]


def evaluate_result(result: PipelineResult, truth: list[dict]) -> dict:
    assert result.document is not None
    blocks = {b.id: b for b in result.document.blocks}
    by_block: dict[str, list] = {}
    for f in result.findings:
        by_block.setdefault(f.block_id, []).append(f)

    occ_total: dict[str, int] = {}
    occ_cov: dict[str, int] = {}
    occ_cov_typed: dict[str, int] = {}
    missed: list[dict] = []
    gt_spans: dict[str, list[tuple[int, int]]] = {}
    values_not_extracted: list[dict] = []
    for t in truth:
        typ, val = t["type"], t["value"]
        found_any = False
        for bid, b in blocks.items():
            for s, e in _occurrences(b.text, val):
                found_any = True
                gt_spans.setdefault(bid, []).append((s, e))
                occ_total[typ] = occ_total.get(typ, 0) + 1
                fs = by_block.get(bid, [])
                over = [f for f in fs if min(e, f.end) - max(s, f.start) >= 0.5 * (e - s)]
                if over:
                    occ_cov[typ] = occ_cov.get(typ, 0) + 1
                    if any(f.type == typ for f in over):
                        occ_cov_typed[typ] = occ_cov_typed.get(typ, 0) + 1
                else:
                    missed.append({"type": typ, "locator": b.locator.label(), "block_id": bid, "start": s, "end": e})
        if not found_any:
            values_not_extracted.append({"type": typ, "length": len(val)})

    # precision: findings that overlap no GT occurrence
    fp: list[dict] = []
    tp = 0
    per_type_tp: dict[str, int] = {}
    per_type_n: dict[str, int] = {}
    for f in result.findings:
        per_type_n[f.type] = per_type_n.get(f.type, 0) + 1
        ok = any(min(f.end, e) - max(f.start, s) > 0 for s, e in gt_spans.get(f.block_id, []))
        if ok:
            tp += 1
            per_type_tp[f.type] = per_type_tp.get(f.type, 0) + 1
        else:
            fp.append({"type": f.type, "locator": f.locator.label(), "block_id": f.block_id, "start": f.start, "end": f.end,
                       "confidence": f.confidence, "detectors": f.detectors, "token": f.token})

    # leak: GT occurrences still readable in the sanitised text
    san_text = "\n".join(b.text for b in result.sanitized_blocks)
    leaked = 0
    total_vals = 0
    for t in truth:
        total_vals += 1
        if _occurrences(san_text, t["value"]):
            leaked += 1

    types = sorted(occ_total)
    per_type = {}
    for ty in types:
        n, c = occ_total[ty], occ_cov.get(ty, 0)
        lo, hi = wilson(c, n)
        n_f = per_type_n.get(ty, 0)
        prec = per_type_tp.get(ty, 0) / n_f if n_f else None
        rec = c / n if n else None
        f1 = (2 * prec * rec / (prec + rec)) if prec and rec else None
        per_type[ty] = {"occurrences": n, "covered": c, "recall": rec, "recall_ci95": [round(lo, 3), round(hi, 3)],
                        "typed_recall": occ_cov_typed.get(ty, 0) / n if n else None, "precision": prec, "f1": f1}
    N, C = sum(occ_total.values()), sum(occ_cov.values())
    lo, hi = wilson(C, N)
    P = tp / len(result.findings) if result.findings else None
    R = C / N if N else None
    return {
        "status": result.status.value,
        "gt_values": len(truth), "gt_occurrences": N, "covered": C,
        "recall": R, "recall_ci95": [round(lo, 3), round(hi, 3)],
        "precision": P, "f1": (2 * P * R / (P + R)) if P and R else None,
        "leaked_values_in_sanitised_text": leaked, "leak_rate": leaked / total_vals if total_vals else 0.0,
        "gt_values_not_extracted": len(values_not_extracted),
        "per_type": per_type, "missed": missed, "false_positives": fp,
    }
