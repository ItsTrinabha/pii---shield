"""Redacted output FILE in the original format. Fail closed: the written file is re-extracted and re-scanned, and it is
only returned if that second scan finds nothing left. PDF text is removed (PyMuPDF redactions, scanned pages blacked
out from OCR word boxes); DOCX/PPTX text is replaced paragraph by paragraph; images that carry findings are blanked."""

from __future__ import annotations

import io
import re
import zipfile

from lxml import etree

from .errors import BlockedError
from .models import PipelineResult, Status
from .settings import Settings

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_TOKEN = re.compile(r"\[?[A-Z_]+_\d+\]?")
_META ={"dc:creator", "cp:lastModifiedBy", "dc:title", "dc:subject", "cp:keywords", "dc:description"}


def _token_map(result: PipelineResult) -> dict[str, str]:
    blocks = {b.id: b for b in result.document.blocks}
    m: dict[str, str] = {}
    for f in result.findings:
        v = blocks[f.block_id].text[f.start:f.end].strip()
        if v and f.token:
            m.setdefault(v, f.token)
    return m


def _replace_paragraphs(root, ptag: str, ttag: str, rx: re.Pattern, tokens: dict[str, str]) -> None:
    for p in root.iter(ptag):
        ts = [t for t in p.iter(ttag)]
        joined = "".join(t.text or "" for t in ts)
        if ts and rx.search(joined):  # replaced in the first run, others emptied (formatting inside a hit paragraph is lost)
            ts[0].text = rx.sub(lambda m: tokens[m.group(0)], joined)
            for t in ts[1:]:
                t.text = ""


def _blank_image(blob: bytes) -> bytes:
    from PIL import Image

    with Image.open(io.BytesIO(blob)) as im:
        out, fmt = Image.new("RGB", im.size, (0, 0, 0)), im.format or "PNG"
    buf = io.BytesIO()
    out.save(buf, format=fmt)
    return buf.getvalue()


def _redact_ooxml(result: PipelineResult, data: bytes) -> bytes:
    tokens = _token_map(result)
    rx = re.compile("|".join(re.escape(v) for v in sorted(tokens, key=len, reverse=True))) if tokens else None
    bad_images = {f.locator.part[len("image:"):] for f in result.findings if f.locator.part.startswith("image:")}
    zin = zipfile.ZipFile(io.BytesIO(data))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            body, n = zin.read(info.filename), info.filename
            if n in bad_images:
                body = _blank_image(body)
            elif n.endswith(".xml") and n.startswith(("word/", "ppt/")) and rx:
                root = etree.fromstring(body, etree.XMLParser(resolve_entities=False, no_network=True))
                _replace_paragraphs(root, f"{{{_W}}}p", f"{{{_W}}}t", rx, tokens)
                _replace_paragraphs(root, f"{{{_A}}}p", f"{{{_A}}}t", rx, tokens)
                body = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
            elif n == "docProps/core.xml":
                root = etree.fromstring(body, etree.XMLParser(resolve_entities=False, no_network=True))
                for el in root:
                    if etree.QName(el).localname in {"creator", "lastModifiedBy", "title", "subject", "keywords", "description"}:
                        el.text = ""
                body = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
            zout.writestr(info.filename, body)
    return buf.getvalue()


def _redact_pdf(result: PipelineResult, data: bytes) -> bytes:
    import pymupdf

    doc = pymupdf.open(stream=data, filetype="pdf")
    blocks = {b.id: b for b in result.document.blocks}
    for f in result.findings:
        b = blocks[f.block_id]
        page = doc[(f.locator.index or 1) - 1]
        if b.geometry:  # OCR text: cover the word boxes, scaled from render pixels to PDF points
            k = 72.0 / (b.render_dpi or 250)
            for w in b.geometry:
                if w.start < f.end and f.start < w.end:
                    page.add_redact_annot(pymupdf.Rect(w.x0 * k, w.y0 * k, w.x1 * k, w.y1 * k) + (-1, -1, 1, 1), fill=(0, 0, 0))
        else:
            for r in page.search_for(b.text[f.start:f.end].strip()):
                page.add_redact_annot(r, fill=(0, 0, 0))
    for page in doc:
        page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_PIXELS)
    doc.set_metadata({})
    doc.scrub()
    return doc.tobytes(garbage=4, deflate=True)


def redact_file(result: PipelineResult, approved_by: str | None = None, settings: Settings | None = None,
                max_rounds: int = 3) -> bytes:
    """Return the redacted file. Same release rules as release(); raises BlockedError if the re-scan still finds anything."""
    from .pipeline import process_bytes

    if result.status == Status.BLOCKED or (result.status == Status.REVIEW and not approved_by):
        raise BlockedError(f"document is {result.status.value}: redacted file not produced")
    doc = result.document
    assert doc is not None and doc.source_bytes
    cur, data = result, doc.source_bytes
    # Redacting changes the page, and OCR can then read text it missed the first time (small print next to a box that
    # is now black). Whatever a re-scan finds is redacted too, for a few rounds; the file is returned only when a
    # re-scan comes back clean.
    for _ in range(max_rounds):
        out = _redact_pdf(cur, data) if doc.file_type == "pdf" else _redact_ooxml(cur, data)
        again = process_bytes(out, doc.file_name, settings)
        if again.status == Status.BLOCKED or again.document is None:
            raise BlockedError(f"redacted file could not be re-scanned ({again.status.value}); not released")
        blocks = {b.id: b for b in again.document.blocks}
        # our own placeholders ("[EMAIL_1]") can look like an email/phone to a recogniser: they are not leftovers
        left = [f for f in again.findings if not _TOKEN.fullmatch(blocks[f.block_id].text[f.start:f.end].strip())]
        if not left:
            return out
        cur, data = again.model_copy(update={"findings": left}), out
    raise BlockedError(f"redacted file still contains {len(left)} finding(s) after {max_rounds} rounds; not released")
