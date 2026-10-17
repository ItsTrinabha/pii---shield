"""Command line: python -m pii_shield scan FILE [--out DIR] [--approve NAME]."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .errors import BlockedError
from .pipeline import process_path, release
from .reporting import audit_html, audit_json
from .settings import Settings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cloak", description="Local, fail-closed PII sanitising gateway")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sc = sub.add_parser("scan", help="scan a PDF/PPTX/DOCX and write sanitised text + audit report")
    sc.add_argument("files", nargs="+")
    sc.add_argument("--out", default="out")
    sc.add_argument("--redact-file", action="store_true", help="also write the redacted file (re-scanned before it is written)")
    sc.add_argument("--deep", action="store_true", help="also run the GLiNER model (better name recall, ~30 s per 100k chars)")
    sc.add_argument("--approve", help="reviewer name; required to release a REVIEW document")
    a = ap.parse_args(argv)

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    worst = 0
    settings = Settings(use_gliner=a.deep)
    for f in a.files:
        t0 = time.time()
        r = process_path(f, settings)
        stem = Path(f).stem
        (out / f"{stem}.audit.json").write_text(audit_json(r), encoding="utf-8")
        (out / f"{stem}.audit.html").write_text(audit_html(r), encoding="utf-8")
        line = f"{Path(f).name}: {r.status.value}  findings={len(r.findings)}  {r.counts_by_type()}  confidentiality={(r.notes.get('confidentiality') or {}).get('label')}"
        try:
            s = release(r, approved_by=a.approve)
            (out / f"{stem}.sanitized.txt").write_text(s.to_text(), encoding="utf-8")
            line += "  -> released"
            if a.redact_file:
                from .redact import redact_file

                try:
                    (out / f"{stem}.redacted{Path(f).suffix}").write_bytes(redact_file(r, a.approve, settings))
                    line += " + redacted file"
                except BlockedError as e:
                    line += f"  -> redacted file NOT written ({e})"
                    worst = max(worst, 1)
        except BlockedError as e:
            line += f"  -> NOT released ({e})"
            worst = max(worst, 2 if r.status.value == "BLOCKED" else 1)
        print(f"{line}  [{time.time() - t0:.1f}s]")
    return worst


if __name__ == "__main__":
    sys.exit(main())
