"""Command line: python -m pii_shield scan FILE [--out DIR] [--approve NAME]."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .errors import BlockedError
from .pipeline import process_path, release
from .reporting import audit_html, audit_json


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pii-shield", description="Fail-closed PII sanitising gateway")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sc = sub.add_parser("scan", help="scan a PDF/PPTX/DOCX and write sanitised text + audit report")
    sc.add_argument("files", nargs="+")
    sc.add_argument("--out", default="out")
    sc.add_argument("--approve", help="reviewer name; required to release a REVIEW document")
    a = ap.parse_args(argv)

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    worst = 0
    for f in a.files:
        r = process_path(f)
        stem = Path(f).stem
        (out / f"{stem}.audit.json").write_text(audit_json(r), encoding="utf-8")
        (out / f"{stem}.audit.html").write_text(audit_html(r), encoding="utf-8")
        line = f"{Path(f).name}: {r.status.value}  findings={len(r.findings)}  {r.counts_by_type()}"
        try:
            s = release(r, approved_by=a.approve)
            (out / f"{stem}.sanitized.txt").write_text(s.to_text(), encoding="utf-8")
            line += "  -> released"
        except BlockedError as e:
            line += f"  -> NOT released ({e})"
            worst = max(worst, 2 if r.status.value == "BLOCKED" else 1)
        print(line)
    return worst


if __name__ == "__main__":
    sys.exit(main())
