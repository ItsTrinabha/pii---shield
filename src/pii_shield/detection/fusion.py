"""Entity fusion: merge overlapping candidates, resolve cross-type conflicts, combine evidence (noisy-OR)."""

from __future__ import annotations

from .patterns import Cand

# Higher wins when two DIFFERENT types claim the same characters.
PRIORITY = {
    "SECRET": 10, "EMAIL": 10, "SSN": 9, "GOV_ID": 9, "TAX_ID": 9, "PASSPORT": 9, "FINANCIAL_ACCOUNT": 9, "EMPLOYEE_ID": 9,
    "DATE_OF_BIRTH": 8, "PHONE": 8, "ADDRESS": 7, "IP_ADDRESS": 5, "TECH_ID": 5, "PERSON": 3, "GENERIC_ID": 2,
}


def _family(det: str) -> str:
    return det.split(":", 1)[0]


def _noisy_or(items: list[Cand]) -> float:
    best: dict[str, float] = {}
    for c in items:
        f = _family(c.detector)
        best[f] = max(best.get(f, 0.0), c.conf)
    p = 1.0
    for v in best.values():
        p *= 1.0 - min(v, 0.99)
    return min(0.99, 1.0 - p)


def _merge_same_type(cands: list[Cand]) -> list[Cand]:
    out: list[Cand] = []
    by_type: dict[str, list[Cand]] = {}
    for c in cands:
        by_type.setdefault(c.type, []).append(c)
    for typ, items in by_type.items():
        items.sort(key=lambda c: (c.start, -c.end))
        group: list[Cand] = []
        gend = -1
        for c in items:
            if group and c.start < gend:
                group.append(c)
                gend = max(gend, c.end)
            else:
                if group:
                    out.append(_collapse(typ, group))
                group, gend = [c], c.end
        if group:
            out.append(_collapse(typ, group))
    return out


def _collapse(typ: str, group: list[Cand]) -> Cand:
    if len(group) == 1:
        return group[0]
    # span: for PERSON prefer the widest span from a strong detector; otherwise union
    s = min(c.start for c in group)
    e = max(c.end for c in group)
    key = next((c.key for c in sorted(group, key=lambda c: -c.conf) if c.key), "")
    dets = sorted({c.detector for c in group})
    return Cand(typ, s, e, _noisy_or(group), "+".join(dets), key=key)


def fuse(cands: list[Cand]) -> list[Cand]:
    merged = _merge_same_type(cands)
    # cross-type conflicts: strongest claim keeps the characters
    merged.sort(key=lambda c: (-PRIORITY.get(c.type, 1), -c.conf, -(c.end - c.start), c.start))
    kept: list[Cand] = []
    for c in merged:
        clash = [k for k in kept if c.start < k.end and k.start < c.end]
        if not clash:
            kept.append(c)
            continue
        # a lower-priority candidate that only partly overlaps keeps its non-overlapping remainder if substantial
        k = clash[0]
        if PRIORITY.get(c.type, 1) == PRIORITY.get(k.type, 1) and c.conf > k.conf and (c.end - c.start) > (k.end - k.start):
            kept.remove(k)
            kept.append(c)
    kept.sort(key=lambda c: c.start)
    return kept
