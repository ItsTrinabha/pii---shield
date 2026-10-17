"""PDF extraction: native text layer where it exists, OCR where it does not (the Cadence policy is 100% scanned)."""

from __future__ import annotations

import re

import pymupdf
from rapidfuzz import fuzz

from ..errors import ExtractionError, SecurityError
from ..models import Block, DocStats, ExtractedDocument, Locator, WordBox
from ..security import safe_name, sha256_hex
from ..settings import Settings
from .ocr import OcrPage, ocr_pdf_pages

_WS = re.compile(r"\s+")


def _norm(s: str) -> str:
    return _WS.sub(" ", s).strip().lower()


def extract_pdf(data: bytes, file_name: str, settings: Settings) -> ExtractedDocument:
    name = safe_name(file_name)
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as e:  # noqa: BLE001
        raise ExtractionError("PDF could not be opened (corrupt or unsupported)", "CORRUPT_FILE") from e
    try:
        if doc.needs_pass or doc.is_encrypted:
            raise SecurityError("PDF is password-protected / encrypted: content cannot be inspected", "ENCRYPTED")
        n_pages = doc.page_count
        if n_pages == 0:
            raise ExtractionError("PDF has no pages", "EMPTY_DOCUMENT")
        if n_pages > settings.limits.max_pdf_pages:
            raise SecurityError("PDF exceeds page limit", "TOO_LARGE")

        blocks: list[Block] = []
        warnings: list[str] = []
        stats = DocStats(page_count=n_pages)
        order = 0

        def add(text: str, loc: Locator, source: str = "native", **kw) -> Block:
            nonlocal order
            b = Block(id=loc.block_id, text=text, locator=loc, source=source, order=order, **kw)
            order += 1
            blocks.append(b)
            return b

        # ---- document-level: metadata, outline, attachments --------------------------------------------
        for k, v in (doc.metadata or {}).items():
            if v and k not in ("format", "encryption"):
                add(str(v), Locator(file=name, unit="metadata", part=k, block_id=f"meta-{k}"), "metadata")
        try:
            for lvl, title, pno in doc.get_toc():
                if title.strip():
                    add(title, Locator(file=name, unit="outline", index=pno or None, block_id=f"toc-{order}"), "native")
        except Exception:  # noqa: BLE001
            warnings.append("outline could not be read")
        try:
            emb = doc.embfile_names()
        except Exception:  # noqa: BLE001
            emb = []
        if emb:
            stats.unsupported_media.append(f"{len(emb)} embedded file(s) in PDF were not analysed")

        # ---- per page native pass -----------------------------------------------------------------------
        native_chars: dict[int, int] = {}
        page_blocks: dict[int, list[Block]] = {}
        needs_ocr: list[int] = []
        hybrid: set[int] = set()
        for i in range(n_pages):
            page = doc[i]
            pno = i + 1
            pb: list[Block] = []
            nchars = 0
            for k, blk in enumerate(page.get_text("blocks", sort=True)):
                x0, y0, x1, y1, txt, bno, btype = blk[:7]
                if btype != 0:
                    continue
                t = txt.strip("\n")
                if not t.strip():
                    continue
                nchars += len(_WS.sub("", t))
                loc = Locator(file=name, unit="page", index=pno, part="", block_id=f"p{pno}-n{k}")
                pb.append(Block(id=loc.block_id, text=t, locator=loc, source="native", order=0))
            native_chars[pno] = nchars
            page_blocks[pno] = pb
            # annotations / form fields / links can hold personal data too
            try:
                for a, annot in enumerate(page.annots() or []):
                    c = (annot.info or {}).get("content") or ""
                    t = (annot.info or {}).get("title") or ""
                    for part, val in (("annotation", c), ("annotation-author", t)):
                        if val.strip():
                            loc = Locator(file=name, unit="page", index=pno, part=part, block_id=f"p{pno}-a{a}{part[-1]}")
                            pb.append(Block(id=loc.block_id, text=val, locator=loc, source="native", order=0))
                for w, wd in enumerate(page.widgets() or []):
                    v = wd.field_value
                    if isinstance(v, str) and v.strip():
                        loc = Locator(file=name, unit="page", index=pno, part="form-field", block_id=f"p{pno}-w{w}")
                        pb.append(Block(id=loc.block_id, text=v, locator=loc, source="native", order=0))
                for link_index, link in enumerate(page.get_links()):
                    uri = link.get("uri")
                    if uri and uri.lower().startswith(("mailto:", "tel:", "http")):
                        loc = Locator(file=name, unit="page", index=pno, part="link", block_id=f"p{pno}-l{link_index}")
                        pb.append(Block(id=loc.block_id, text=uri, locator=loc, source="native", order=0))
            except Exception:  # noqa: BLE001
                warnings.append(f"page {pno}: annotations/links could not be read")

            if nchars < settings.min_native_chars_for_text_page:
                needs_ocr.append(i)
            else:
                # text page that also carries large images: OCR it too, keep only text not in the text layer
                try:
                    area = page.rect.width * page.rect.height
                    big = False
                    for img in page.get_image_info():
                        bx = pymupdf.Rect(img["bbox"])
                        if bx.width * bx.height >= 0.05 * area and min(bx.width, bx.height) > 40:
                            big = True
                            break
                    if big:
                        hybrid.add(i)
                        needs_ocr.append(i)
                except Exception:  # noqa: BLE001
                    pass
    finally:
        doc.close()

    # ---- OCR pass (parallel) -----------------------------------------------------------------------------
    results = ocr_pdf_pages(data, needs_ocr, settings)
    ocr_pages: dict[int, OcrPage] = {}
    for idx, page_res, err in results:
        if err or page_res is None:
            raise ExtractionError(f"OCR failed on page {idx + 1} ({err})", err or "OCR_FAILED")
        ocr_pages[idx + 1] = page_res

    confs: list[float] = []
    for pno in range(1, n_pages + 1):
        pb = page_blocks.get(pno, [])
        res = ocr_pages.get(pno)
        if res is not None:
            stats.ocr_pages += 1
            if res.mean_confidence is not None:
                confs.append(res.mean_confidence)
                if res.mean_confidence < settings.low_ocr_confidence:
                    stats.low_confidence_pages.append(pno)
            if res.ink_coverage is not None:
                stats.ink_coverage[pno] = round(res.ink_coverage, 4)
            native_all = _norm(" ".join(b.text for b in pb if b.source == "native"))
            for k, para in enumerate(res.paragraphs):
                if (pno - 1) in hybrid and native_all and fuzz.partial_ratio(_norm(para.text), native_all) >= 92:
                    continue  # already present in the text layer
                loc = Locator(file=name, unit="page", index=pno, part="", block_id=f"p{pno}-o{k}")
                pb.append(
                    Block(
                        id=loc.block_id,
                        text=para.text,
                        locator=loc,
                        source="ocr",
                        ocr_confidence=round(para.confidence, 1),
                        geometry=[WordBox(start=s, end=e, x0=x0, y0=y0, x1=x1, y1=y1) for (s, e, x0, y0, x1, y1) in para.words],
                        render_dpi=settings.ocr_dpi,
                    )
                )
            if not res.paragraphs and native_chars.get(pno, 0) < settings.min_native_chars_for_text_page:
                warnings.append(f"page {pno}: no text recognised (blank page or unreadable content)")
        for b in pb:
            b.order = order_counter(blocks)
            blocks.append(b)

    if not any(b.text.strip() for b in blocks if b.locator.unit in ("page",)):
        warnings.append("no page text could be extracted")

    stats.block_count = len(blocks)
    stats.ocr_blocks = sum(1 for b in blocks if b.source == "ocr")
    stats.native_chars = sum(len(b.text) for b in blocks if b.source != "ocr")
    stats.ocr_chars = sum(len(b.text) for b in blocks if b.source == "ocr")
    stats.mean_ocr_confidence = round(sum(confs) / len(confs), 1) if confs else None
    return ExtractedDocument(
        file_name=name, file_type="pdf", sha256=sha256_hex(data), size_bytes=len(data),
        blocks=blocks, stats=stats, warnings=warnings, source_bytes=data,
    )


def order_counter(blocks: list[Block]) -> int:
    return (blocks[-1].order + 1) if blocks else 0
