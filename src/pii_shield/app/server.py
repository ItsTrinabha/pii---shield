"""Local web UI: a Starlette JSON API plus a static single-page app (src/pii_shield/app/static).

Run: python -m pii_shield.app   (binds 127.0.0.1 only)

Raw values leave this process only when the reviewer explicitly asks for them (reveal=1); every default response carries
tokens, types, locations and confidences. Accuracy figures are shown only for files that have ground truth in
data/ground_truth (rule 6: measure, don't claim); other files get verification-based quality signals, labelled as such.
"""

from __future__ import annotations

import asyncio
import io
import re
import secrets
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from ..errors import BlockedError
from ..models import Locator, PipelineResult, SanitizedText, Status
from ..pipeline import process_bytes, release
from ..reporting import audit_html, audit_json
from ..settings import Limits, Settings
from .view import hidden_sanitized_blocks

STATIC = Path(__file__).with_name("static")
TRUTH_DIR = Path(__file__).resolve().parents[3] / "data" / "ground_truth"
_TOKEN = re.compile(r"\[[A-Z_]+_\d+\]")
_SCAN = ThreadPoolExecutor(max_workers=1)  # the pipeline already uses every core; scans queue instead of competing
_WORK = ThreadPoolExecutor(max_workers=2)  # page renders, redacted files
_render_lock = Lock()  # PyMuPDF is not thread-safe


@dataclass
class Entry:
    id: str
    name: str
    result: PipelineResult
    elapsed: float
    created: float
    deep: bool
    accuracy: dict | None = None
    released: SanitizedText | None = None
    approved_by: str | None = None
    redacted: bytes | None = None
    pages: dict = field(default_factory=dict)  # (page, reveal) -> png


DOCS: dict[str, Entry] = {}


# ---------------------------------------------------------------------------------------------------------------- helpers
def _group(loc: Locator) -> tuple[tuple, str]:
    """Where a finding sits, as a reviewer would name it: Page 3, Slide 5, Body, Image · image4.png."""
    if loc.index is not None:
        unit = {"page": "Page", "slide": "Slide"}.get(loc.unit, loc.unit.title())
        return (0, loc.index, ""), f"{unit} {loc.index}"
    if loc.part.startswith("image:"):
        name = loc.part.rsplit("/", 1)[-1]
        return (2, 0, name), f"Image · {name}"
    return (1, 0, loc.unit), loc.unit.title()


def _accuracy(r: PipelineResult, name: str) -> dict | None:
    tf = TRUTH_DIR / f"{name}.jsonl"
    if not tf.exists():
        return None
    from ..eval.metrics import evaluate_result, load_truth

    m = evaluate_result(r, load_truth(tf))
    blocks = {b.id: b for b in r.document.blocks} if r.document else {}

    def where(x: dict) -> dict:
        b = blocks.get(x.get("block_id", ""))
        return {"type": x.get("type"), "block_id": x.get("block_id"), "start": x.get("start"), "end": x.get("end"),
                "where": _group(b.locator)[1] if b else x.get("locator", ""), "locator": x.get("locator", "")}

    return {
        "truth_file": tf.name,
        "recall": m["recall"], "recall_ci95": m["recall_ci95"], "precision": m["precision"], "f1": m["f1"],
        "gt_values": m["gt_values"], "leaked": m["leaked_values_in_sanitised_text"],
        "not_extracted": m["gt_values_not_extracted"],
        "per_type": m["per_type"],
        "missed": [where(x) for x in m["missed"]],
        "false_positives": [where(x) for x in m["false_positives"]],
    }


def _quality(r: PipelineResult) -> dict:
    """Signals that do not need ground truth. They describe how sure the system is, not how accurate it is."""
    fs = r.findings
    st = r.document.stats if r.document else None
    v = r.verification
    ink = list(st.ink_coverage.values()) if st else []
    return {
        "mean_confidence": round(sum(f.confidence for f in fs) / len(fs), 3) if fs else None,
        "high_confidence_share": round(sum(f.confidence >= 0.8 for f in fs) / len(fs), 3) if fs else None,
        "verifier_hard": len(v.hard_hits) if v else 0,
        "verifier_soft": len(v.soft_hits) if v else 0,
        "verifier_rules": len(v.rules_run) if v else 0,
        "review_candidates": len(r.notes.get("review_candidates", [])),
        "forced_redactions": r.notes.get("forced_redactions", 0),
        "mean_ocr_confidence": round(st.mean_ocr_confidence, 1) if st and st.mean_ocr_confidence else None,
        "min_ink_coverage": round(min(ink), 3) if ink else None,
        "low_confidence_pages": st.low_confidence_pages if st else [],
        "unsupported_media": len(st.unsupported_media) if st else 0,
    }


def _groups(r: PipelineResult) -> list[dict]:
    if r.document is None:
        return []
    out: dict[tuple, dict] = {}
    blocks = r.document.blocks
    by_id = {b.id: b for b in blocks}
    for b in blocks:
        key, label = _group(b.locator)
        g = out.setdefault(key, {"label": label, "index": b.locator.index, "unit": b.locator.unit, "hits": 0,
                                 "by_type": {}, "conf": [], "blocks": 0, "chars": 0, "ocr_blocks": 0, "ocr_conf": [],
                                 "verifier": 0, "review": 0, "first_block": b.id})
        g["blocks"] += 1
        g["chars"] += len(b.text)
        if b.source == "ocr":
            g["ocr_blocks"] += 1
            if b.ocr_confidence is not None:
                g["ocr_conf"].append(b.ocr_confidence)
    for f in r.findings:
        b = by_id.get(f.block_id)
        if not b:
            continue
        g = out[_group(b.locator)[0]]
        g["hits"] += 1
        g["by_type"][f.type] = g["by_type"].get(f.type, 0) + 1
        g["conf"].append(f.confidence)
    if r.verification:
        for h in r.verification.hard_hits + r.verification.soft_hits:
            b = by_id.get(h.block_id)
            if b:
                out[_group(b.locator)[0]]["verifier"] += 1
    for c in r.notes.get("review_candidates", []):
        b = by_id.get(c["block_id"])
        if b:
            out[_group(b.locator)[0]]["review"] += 1
    ink = r.document.stats.ink_coverage
    res = []
    for key in sorted(out):
        g = out[key]
        conf, oc = g.pop("conf"), g.pop("ocr_conf")
        g["mean_conf"] = round(sum(conf) / len(conf), 3) if conf else None
        g["min_conf"] = round(min(conf), 3) if conf else None
        g["ocr_conf"] = round(sum(oc) / len(oc), 1) if oc else None
        g["ink"] = ink.get(g["index"]) if g["index"] is not None and g["unit"] == "page" else None
        g["key"] = f"{key[0]}-{key[1]}-{key[2]}"
        res.append(g)
    return res


def _summary(e: Entry) -> dict:
    r = e.result
    doc = r.document
    distinct = {(f.type, f.fingerprint) for f in r.findings}
    st = doc.stats if doc else None
    unit = "Pages" if doc and doc.file_type == "pdf" else "Slides" if doc and doc.file_type == "pptx" else "Sections"
    groups = _groups(r)
    return {
        "id": e.id, "name": e.name, "type": doc.file_type if doc else Path(e.name).suffix.lstrip("."),
        "size": doc.size_bytes if doc else None, "status": r.status.value, "reasons": r.reasons,
        "created": e.created, "elapsed": round(e.elapsed, 1), "deep": e.deep,
        "approved_by": e.approved_by, "released": e.released is not None,
        "needs_approval": r.status == Status.REVIEW and e.released is None,
        "counts": {"findings": len(r.findings), "distinct": len(distinct), "by_type": r.counts_by_type(),
                   "distinct_by_type": _distinct_by_type(r)},
        "units": {"label": unit, "count": (st.page_count if st and st.page_count else len(groups))},
        "stats": st.model_dump() if st else None,
        "confidentiality": r.notes.get("confidentiality"),
        "accuracy": e.accuracy,
        "quality": _quality(r),
        "timings": r.timings,
        "groups": groups,
        "has_pages": bool(doc and doc.file_type == "pdf"),
        "warnings": doc.warnings if doc else [],
        "config_digest": r.config_digest,
    }


def _distinct_by_type(r: PipelineResult) -> dict[str, int]:
    seen: dict[str, set] = {}
    for f in r.findings:
        seen.setdefault(f.type, set()).add(f.fingerprint)
    return {k: len(v) for k, v in sorted(seen.items(), key=lambda kv: -len(kv[1]))}


def _findings(r: PipelineResult, reveal: bool) -> list[dict]:
    blocks = {b.id: b for b in r.document.blocks} if r.document else {}
    out = []
    for f in r.findings:
        b = blocks.get(f.block_id)
        row = {"id": f.id, "type": f.type, "token": f.token, "confidence": round(f.confidence, 3),
               "detectors": f.detectors, "action": f.action, "block_id": f.block_id, "start": f.start, "end": f.end,
               "where": _group(f.locator)[1], "locator": f.locator.label(), "part": f.locator.part,
               "index": f.locator.index, "ocr": f.ocr_derived, "length": f.length, "fingerprint": f.fingerprint[:12],
               "note": f.note, "source": b.source if b else ""}
        if reveal and b:
            row["value"] = b.text[f.start:f.end]
        out.append(row)
    return out


def _blocks(r: PipelineResult, reveal: bool) -> list[dict]:
    if r.document is None:
        return []
    san = {s.id: s.text for s in r.sanitized_blocks}
    hidden = hidden_sanitized_blocks(r, reveal)
    spans: dict[str, list] = {}
    for f in r.findings:
        spans.setdefault(f.block_id, []).append([f.start, f.end, f.type, f.token, round(f.confidence, 2), f.id])
    review: dict[str, list] = {}
    for c in r.notes.get("review_candidates", []):
        review.setdefault(c["block_id"], []).append([c["start"], c["end"], c["type"], round(c["confidence"], 2)])
    out = []
    for b in r.document.blocks:
        _, label = _group(b.locator)
        row = {"id": b.id, "group": label, "part": b.locator.part, "unit": b.locator.unit, "index": b.locator.index,
               "source": b.source, "ocr_conf": round(b.ocr_confidence, 1) if b.ocr_confidence is not None else None,
               "hits": len(spans.get(b.id, []))}
        if reveal:
            row["text"] = b.text
            row["spans"] = sorted(spans.get(b.id, []))
            row["review"] = review.get(b.id, [])
        elif b.id in hidden:
            row["text"] = ""
            row["hidden"] = True
        else:
            row["text"] = san.get(b.id, "")
        out.append(row)
    return out


def _render_page(e: Entry, page: int, reveal: bool) -> bytes:
    """PDF page with findings overlaid: solid boxes (the redaction preview) or tinted boxes when revealing."""
    import pymupdf
    from PIL import Image, ImageDraw

    key = (page, reveal)
    if key in e.pages:
        return e.pages[key]
    r = e.result
    doc_meta = r.document
    assert doc_meta is not None and doc_meta.source_bytes is not None
    dpi = 110
    with _render_lock:
        pdf = pymupdf.open(stream=doc_meta.source_bytes, filetype="pdf")
        try:
            pg = pdf[page - 1]
            pix = pg.get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB, alpha=False)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            blocks = {b.id: b for b in doc_meta.blocks}
            rects: list[tuple[float, float, float, float, str]] = []
            for f in r.findings:
                b = blocks.get(f.block_id)
                if not b or b.locator.index != page:
                    continue
                if b.geometry:
                    k = dpi / (b.render_dpi or 250)
                    for w in b.geometry:
                        if w.start < f.end and f.start < w.end:
                            rects.append((w.x0 * k, w.y0 * k, w.x1 * k, w.y1 * k, f.type))
                else:
                    k = dpi / 72.0
                    for q in pg.search_for(b.text[f.start:f.end].strip()):
                        rects.append((q.x0 * k, q.y0 * k, q.x1 * k, q.y1 * k, f.type))
        finally:
            pdf.close()
    over = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    for x0, y0, x1, y1, typ in rects:
        box = (x0 - 2, y0 - 2, x1 + 2, y1 + 2)
        if reveal:
            c = _TYPE_RGB.get(typ, (10, 132, 255))
            d.rounded_rectangle(box, radius=3, fill=(*c, 60), outline=(*c, 230), width=2)
        else:
            d.rounded_rectangle(box, radius=3, fill=(22, 34, 56, 255))
    img = Image.alpha_composite(img.convert("RGBA"), over).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False)
    e.pages[key] = buf.getvalue()
    return e.pages[key]


_TYPE_RGB = {"PERSON": (10, 132, 255), "EMAIL": (94, 92, 230), "PHONE": (48, 176, 199), "EMPLOYEE_ID": (52, 199, 89),
             "SSN": (255, 69, 58), "PASSPORT": (255, 55, 95), "TAX_ID": (255, 149, 0), "DATE_OF_BIRTH": (191, 90, 242),
             "ADDRESS": (162, 132, 94), "FINANCIAL_ACCOUNT": (255, 159, 10), "IP_ADDRESS": (100, 210, 255)}


def _entry(request: Request) -> Entry:
    e = DOCS.get(request.path_params["doc_id"])
    if e is None:
        raise KeyError
    return e


def _err(msg: str, code: int) -> JSONResponse:
    return JSONResponse({"error": msg}, status_code=code)


# --------------------------------------------------------------------------------------------------------------- routes
async def index(request: Request) -> Response:
    resp = FileResponse(STATIC / "index.html")
    if "pii_csrf" not in request.cookies:
        resp.set_cookie("pii_csrf", secrets.token_urlsafe(24), samesite="strict", httponly=False)
    return resp


def _csrf_ok(request: Request) -> bool:
    c = request.cookies.get("pii_csrf")
    return bool(c) and secrets.compare_digest(c, request.headers.get("x-csrf-token", ""))


async def scan(request: Request) -> Response:
    if not _csrf_ok(request):
        return _err("missing or invalid CSRF token", 403)
    form = await request.form(max_files=1, max_part_size=Limits().max_upload_bytes)
    up = form.get("file")
    if up is None or isinstance(up, str):
        return _err("no file uploaded", 400)
    name = Path(up.filename or "upload").name
    data = await up.read()
    deep = form.get("deep") == "1"
    settings = Settings(use_gliner=deep)

    def run() -> Entry:
        t0 = time.time()
        r = process_bytes(data, name, settings)
        e = Entry(id=uuid.uuid4().hex[:12], name=name, result=r, elapsed=time.time() - t0, created=time.time(), deep=deep)
        try:
            e.accuracy = _accuracy(r, name)
        except Exception:  # noqa: BLE001 - a scoring problem must not hide the scan result
            e.accuracy = None
        if r.status == Status.PASS:
            e.released = release(r)
        return e

    e = await asyncio.get_running_loop().run_in_executor(_SCAN, run)
    DOCS[e.id] = e
    return JSONResponse(_summary(e))


async def list_docs(request: Request) -> Response:
    return JSONResponse([_summary(e) for e in sorted(DOCS.values(), key=lambda x: -x.created)])


async def get_doc(request: Request) -> Response:
    try:
        e = _entry(request)
    except KeyError:
        return _err("unknown document", 404)
    reveal = request.query_params.get("reveal") == "1"
    r = e.result
    v = r.verification
    out = _summary(e)
    out["findings"] = _findings(r, reveal)
    out["verification"] = {
        "passed": v.passed if v else None, "rules_run": v.rules_run if v else [],
        "hits": [{"severity": h.severity, "rule": h.rule, "block_id": h.block_id, "where": _group(h.locator)[1],
                  "locator": h.locator.label()} for h in ((v.hard_hits + v.soft_hits) if v else [])],
    }
    out["review_candidates"] = [{**c, "confidence": round(c["confidence"], 2),
                                 "where": c["locator"]} for c in r.notes.get("review_candidates", [])]
    return JSONResponse(out)


async def get_blocks(request: Request) -> Response:
    try:
        e = _entry(request)
    except KeyError:
        return _err("unknown document", 404)
    return JSONResponse(_blocks(e.result, request.query_params.get("reveal") == "1"))


async def get_page(request: Request) -> Response:
    try:
        e = _entry(request)
    except KeyError:
        return _err("unknown document", 404)
    if not (e.result.document and e.result.document.file_type == "pdf"):
        return _err("page images exist for PDF only", 404)
    page = int(request.path_params["page"])
    if not 1 <= page <= max(e.result.document.stats.page_count, 1):
        return _err("no such page", 404)
    reveal = request.query_params.get("reveal") == "1"
    png = await asyncio.get_running_loop().run_in_executor(_WORK, _render_page, e, page, reveal)
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


async def approve(request: Request) -> Response:
    if not _csrf_ok(request):
        return _err("missing or invalid CSRF token", 403)
    try:
        e = _entry(request)
    except KeyError:
        return _err("unknown document", 404)
    body = await request.json()
    name = str(body.get("name", "")).strip()[:80]
    if not name:
        return _err("a reviewer name is required", 400)
    try:
        e.released = release(e.result, approved_by=name)
    except BlockedError as ex:
        return _err(str(ex), 409)
    e.approved_by = name
    return JSONResponse(_summary(e))


async def download(request: Request) -> Response:
    try:
        e = _entry(request)
    except KeyError:
        return _err("unknown document", 404)
    kind = request.path_params["kind"]
    stem = Path(e.name).stem
    if kind == "audit.json":
        return Response(audit_json(e.result), media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{stem}.audit.json"'})
    if kind == "audit.html":
        return Response(audit_html(e.result), media_type="text/html",
                        headers={"Content-Disposition": f'attachment; filename="{stem}.audit.html"'})
    if e.released is None:
        return _err("not released: the document is BLOCKED or still needs a named approval", 409)
    if kind == "sanitized.txt":
        return Response(e.released.to_text(), media_type="text/plain; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{stem}.sanitized.txt"'})
    if kind == "redacted":
        if e.redacted is None:
            from ..redact import redact_file

            try:
                e.redacted = await asyncio.get_running_loop().run_in_executor(
                    _SCAN, redact_file, e.result, e.approved_by, Settings(use_gliner=e.deep))
            except BlockedError as ex:
                return _err(str(ex), 409)
        suffix = Path(e.name).suffix
        mt = {"pdf": "application/pdf",
              "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
              "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation"}.get(suffix[1:], "application/octet-stream")
        return Response(e.redacted, media_type=mt,
                        headers={"Content-Disposition": f'attachment; filename="{stem}.redacted{suffix}"'})
    return _err("unknown download", 404)


async def delete_doc(request: Request) -> Response:
    if not _csrf_ok(request):
        return _err("missing or invalid CSRF token", 403)
    DOCS.pop(request.path_params["doc_id"], None)
    return JSONResponse({"ok": True})


def create_app() -> Starlette:
    return Starlette(routes=[
        Route("/", index),
        Route("/api/scan", scan, methods=["POST"]),
        Route("/api/docs", list_docs),
        Route("/api/docs/{doc_id}", get_doc),
        Route("/api/docs/{doc_id}", delete_doc, methods=["DELETE"]),
        Route("/api/docs/{doc_id}/blocks", get_blocks),
        Route("/api/docs/{doc_id}/page/{page:int}", get_page),
        Route("/api/docs/{doc_id}/approve", approve, methods=["POST"]),
        Route("/api/docs/{doc_id}/download/{kind}", download),
        Mount("/static", StaticFiles(directory=STATIC), name="static"),
    ])


app = create_app()
