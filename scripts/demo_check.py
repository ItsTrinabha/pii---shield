"""Drive the Streamlit app headlessly on every Cadence sample and check the demo path end to end.

Usage: python scripts/demo_check.py [substring]
Prints statuses, counts and booleans only (never document text or values)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "src" / "pii_shield" / "app" / "main.py"
SAMPLES = sorted(p.name for p in (ROOT / "data" / "samples").glob("*") if p.suffix.lower() in (".pdf", ".pptx", ".docx"))


def gt_values(name: str) -> list[str]:
    f = ROOT / "data" / "ground_truth" / f"{name}.jsonl"
    return [json.loads(x)["value"].lower() for x in f.read_text(encoding="utf-8").splitlines() if x.strip()] if f.exists() else []


def check(sample: str) -> dict:
    at = AppTest.from_file(str(APP), default_timeout=1800).run()
    at.sidebar.radio[0].set_value("Cadence sample").run()
    at.sidebar.selectbox[0].set_value(sample).run()
    res: dict = {"sample": sample, "exception": bool(at.exception)}
    res["banner"] = "PASS" if at.success else "REVIEW" if at.warning else "BLOCKED" if at.error else "none"
    res["reveal_default_off"] = next(t for t in at.sidebar.toggle if "Reveal" in t.label).value is False
    labels = [getattr(e, "label", "") or e.proto.label for e in at.get("download_button")]
    res["download_buttons"] = labels
    if res["banner"] == "REVIEW":
        res["released_before_approval"] = any("Sanitised text" in x for x in labels)
        at.text_input[0].set_value("Demo Reviewer").run()
        at.checkbox[-1].check().run()
        labels = [getattr(e, "label", "") or e.proto.label for e in at.get("download_button")]
        res["released_after_approval"] = any("Sanitised text" in x for x in labels)
    previews = [t.value for t in at.text] if hasattr(at, "text") else []
    blob = "\n".join(previews).lower()
    vals = gt_values(sample)
    res["preview_chars"] = len(blob)
    res["gt_values_in_preview"] = sum(1 for v in vals if len(v) > 4 and v in blob)
    res["exception_detail"] = [str(x.value)[:200] for x in at.exception] if at.exception else []
    return res


if __name__ == "__main__":
    pick = sys.argv[1] if len(sys.argv) > 1 else ""
    for s in SAMPLES:
        if pick in s:
            print(json.dumps(check(s)), flush=True)
