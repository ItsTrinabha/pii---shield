"""python -m pii_shield.eval --corpus data/samples --truth data/ground_truth [--out docs/eval.json] [--only pdf]

--render-ocr scores each sample after rendering it to an image-only PDF (LibreOffice + rasterise), i.e. through OCR,
against the same ground truth as the native run: the OCR-vs-native comparison.
"""

from __future__ import annotations

import argparse
import gc
import json
from pathlib import Path

from ..pipeline import process_bytes, process_path
from ..settings import Settings
from .metrics import evaluate_result, load_truth
from .render import ocr_variant
from .structure import reference_units, score, structure_retention


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="data/samples")
    ap.add_argument("--truth", default="data/ground_truth")
    ap.add_argument("--out", default="")
    ap.add_argument("--only", default="")
    # Each OCR worker holds a rendered page plus Tesseract's working set; 2 keeps a full run within laptop memory.
    ap.add_argument("--deep", action="store_true", help="also run GLiNER")
    ap.add_argument("--no-rapidocr", action="store_true", help="ablation: disable the second OCR engine")
    ap.add_argument("--ocr-workers", type=int, default=2)
    ap.add_argument("--render-ocr", action="store_true", help="score the OCR path: render to an image-only PDF first")
    ap.add_argument("--render-dpi", type=int, default=200)
    return ap.parse_args(argv)


def settings_from_args(a: argparse.Namespace) -> Settings:
    return Settings(ocr_workers=max(1, a.ocr_workers), use_gliner=a.deep, use_rapidocr=not a.no_rapidocr)


def main(argv: list[str] | None = None) -> None:
    a = parse_args(argv)
    settings = settings_from_args(a)
    out = {}
    for tf in sorted(Path(a.truth).glob("*.jsonl")):
        name = tf.name[: -len(".jsonl")]
        if a.only and a.only not in name:
            continue
        src = Path(a.corpus) / name
        if not src.exists():
            continue
        if a.render_ocr:
            data, pname = ocr_variant(src, a.render_dpi)
            r = process_bytes(data, pname, settings)
            m = evaluate_result(r, load_truth(tf))
            m["mode"] = f"ocr (rendered, rasterised at {a.render_dpi} dpi)"
            # locators are pages now, so only the found rate of the original's units is meaningful
            m["structure"] = score(reference_units(src.read_bytes(), src.name), r.document) if r.document else None
        else:
            r = process_path(src, settings)
            m = evaluate_result(r, load_truth(tf))
            m["mode"] = "native"
            m["structure"] = structure_retention(src.read_bytes(), src.name, r.document)
        del r  # the extracted document (all blocks, OCR geometry) is not needed once scored
        gc.collect()
        out[name] = m
        pt = ", ".join(f"{k}: R={v['recall']:.3f}" + (f" P={v['precision']:.3f}" if v["precision"] is not None else "")
                       for k, v in m["per_type"].items())
        fmt = lambda x: "n/a" if x is None else f"{x:.3f}"  # noqa: E731
        print(f"{name} [{m['mode']}]\n  status={m['status']} R={fmt(m['recall'])} CI95={m['recall_ci95']} P={fmt(m['precision'])} "
              f"F1={fmt(m['f1'])} leak={m['leaked_values_in_sanitised_text']}/{m['gt_values']} "
              f"missed={len(m['missed'])} fp={len(m['false_positives'])} not_extracted={m['gt_values_not_extracted']}\n  {pt}")
        s = m["structure"]
        if s and a.render_ocr:
            print(f"  content found (original units): {fmt(s['found_rate'])} ({s['found']}/{s['units']})")
        elif s:
            print(f"  structure ({s['unit_level']}): retention={fmt(s['retention'])} ({s['retained']}/{s['units']}) "
                  f"found={fmt(s['found_rate'])} locator={fmt(s['locator_rate'])} order={fmt(s['order_rate'])}")
    if a.out:
        Path(a.out).write_text(json.dumps(out, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
