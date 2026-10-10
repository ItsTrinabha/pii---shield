"""python -m pii_shield.eval --corpus data/samples --truth data/ground_truth [--out docs/eval.json]"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..pipeline import process_path
from .metrics import evaluate_result, load_truth


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="data/samples")
    ap.add_argument("--truth", default="data/ground_truth")
    ap.add_argument("--out", default="")
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    out = {}
    for tf in sorted(Path(a.truth).glob("*.jsonl")):
        name = tf.name[: -len(".jsonl")]
        if a.only and a.only not in name:
            continue
        src = Path(a.corpus) / name
        if not src.exists():
            continue
        r = process_path(src)
        m = evaluate_result(r, load_truth(tf))
        out[name] = m
        pt = ", ".join(f"{k}: R={v['recall']:.3f}" + (f" P={v['precision']:.3f}" if v["precision"] is not None else "")
                       for k, v in m["per_type"].items())
        fmt = lambda x: "n/a" if x is None else f"{x:.3f}"  # noqa: E731
        print(f"{name}\n  status={m['status']} R={fmt(m['recall'])} CI95={m['recall_ci95']} P={fmt(m['precision'])} "
              f"F1={fmt(m['f1'])} leak={m['leaked_values_in_sanitised_text']}/{m['gt_values']} "
              f"missed={len(m['missed'])} fp={len(m['false_positives'])} not_extracted={m['gt_values_not_extracted']}\n  {pt}")
    if a.out:
        Path(a.out).write_text(json.dumps(out, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
