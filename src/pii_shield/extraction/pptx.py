"""PPTX extraction: slides (text frames, grouped shapes, tables, pictures, charts), notes, layouts/masters,
alt text, metadata, hyperlink targets, then an independent XML sweep for anything missed."""

from __future__ import annotations

import io

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.shapes.base import BaseShape

from ..errors import ExtractionError
from ..models import Block, DocStats, ExtractedDocument, Locator
from ..security import safe_name, sha256_hex, validate_zip_package
from ..settings import Settings
from .ooxml import hyperlink_blocks, image_blocks, metadata_blocks, norm, ocr_images, sweep


def _shapes(container):
    for sh in container:
        yield sh
        if sh.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from _shapes(sh.shapes)


def _alt_text(sh: BaseShape) -> list[str]:
    out = []
    try:
        for el in sh._element.xpath(".//p:cNvPr"):
            for k in ("descr", "title"):
                v = el.get(k)
                if v and v.strip():
                    out.append(v.strip())
    except Exception:  # noqa: BLE001
        pass
    return out


def extract_pptx(data: bytes, file_name: str, settings: Settings) -> ExtractedDocument:
    name = safe_name(file_name)
    zf = validate_zip_package(data, "pptx", settings.limits)
    try:
        prs = Presentation(io.BytesIO(data))
    except Exception as e:  # noqa: BLE001
        raise ExtractionError("PPTX could not be parsed", "CORRUPT_FILE") from e

    blocks: list[Block] = []
    stats = DocStats()
    warnings: list[str] = []
    order = 0
    images: dict[str, bytes] = {}
    image_slots: list[tuple[int | None, str, str, int]] = []  # (slide, key, unit, insert_pos_order)

    def add(text: str, slide: int | None, part: str, unit: str = "slide", source: str = "native") -> None:
        nonlocal order
        text = text.replace("\v", "\n")
        if not text.strip():
            return
        loc = Locator(file=name, unit=unit, index=slide, part=part, block_id=f"{unit[0]}{slide or 0}-{order}")
        blocks.append(Block(id=loc.block_id, text=text, locator=loc, source=source, order=order))
        order += 1

    def handle_shape(sh: BaseShape, slide_no: int | None, unit: str) -> None:
        nonlocal order
        sname = sh.name or "shape"
        try:
            if sh.has_text_frame:
                for pi, para in enumerate(sh.text_frame.paragraphs):
                    add(para.text, slide_no, f"shape:{sname}" if pi == 0 else f"shape:{sname} p{pi + 1}", unit)
            if getattr(sh, "has_table", False) and sh.has_table:
                tbl = sh.table
                for ri, row in enumerate(tbl.rows):
                    for ci, cell in enumerate(row.cells):
                        if cell.is_spanned:
                            continue
                        for pi, para in enumerate(cell.text_frame.paragraphs):
                            add(para.text, slide_no, f"table:{sname} r{ri + 1}c{ci + 1}", unit)
            if sh.shape_type == MSO_SHAPE_TYPE.PICTURE:
                blob = sh.image.blob
                key = f"s{slide_no or 0}/{sname}.{sh.image.ext}"
                images[key] = blob
                image_slots.append((slide_no, key, unit, order))
            if getattr(sh, "has_chart", False) and sh.has_chart:
                ch = sh.chart
                if ch.has_title and ch.chart_title.has_text_frame:
                    add(ch.chart_title.text_frame.text, slide_no, f"chart-title:{sname}", unit)
                try:
                    for plot in ch.plots:
                        for cat in plot.categories:
                            add(str(cat), slide_no, f"chart-category:{sname}", unit)
                        for s in plot.series:
                            add(str(s.name), slide_no, f"chart-series:{sname}", unit)
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001
            warnings.append(f"{unit} {slide_no}: shape '{sname}' could not be fully read (completeness sweep covers it)")
        for alt in _alt_text(sh):
            add(alt, slide_no, f"alt-text:{sname}", unit)

    # ---- slides ------------------------------------------------------------------------------------------
    n_slides = len(prs.slides)
    if n_slides == 0:
        raise ExtractionError("presentation has no slides", "EMPTY_DOCUMENT")
    stats.page_count = n_slides
    for si, slide in enumerate(prs.slides, 1):
        if slide._element.get("show") == "0":
            stats.hidden_content_blocks += 1
        for sh in _shapes(slide.shapes):
            if sh.shape_type == MSO_SHAPE_TYPE.GROUP:
                for alt in _alt_text(sh):
                    add(alt, si, f"alt-text:{sh.name}")
                continue
            handle_shape(sh, si, "slide")
        if slide.has_notes_slide:
            ns = slide.notes_slide
            for sh in ns.shapes:
                if sh.has_text_frame and sh.text_frame.text.strip():
                    txt = sh.text_frame.text.strip()
                    if txt.isdigit():
                        continue  # slide-number placeholder
                    add(txt, si, "notes")

    # ---- layouts and masters (footers, headers, boilerplate that renders on slides) -----------------------
    seen_layout: set[str] = set()
    for master in prs.slide_masters:
        for sh in _shapes(master.shapes):
            if sh.has_text_frame and sh.text_frame.text.strip():
                t = sh.text_frame.text.strip()
                if t not in seen_layout:
                    seen_layout.add(t)
                    add(t, None, f"master:{sh.name}", "layout")
        for layout in master.slide_layouts:
            for sh in _shapes(layout.shapes):
                if sh.has_text_frame and sh.text_frame.text.strip():
                    t = sh.text_frame.text.strip()
                    if t not in seen_layout:
                        seen_layout.add(t)
                        add(t, None, f"layout:{layout.name}/{sh.name}", "layout")

    # ---- images: OCR and insert at their slide position ---------------------------------------------------
    img_results, unsupported = ocr_images(images, settings) if images else ({}, [])
    stats.unsupported_media.extend(f"{k}: unsupported image format, not analysed" for k in unsupported)
    for slide_no, key, unit, _pos in image_slots:
        pg = img_results.get(key)
        if pg is None:
            continue
        for b in image_blocks(name, unit, slide_no, key, pg, order):
            blocks.append(b)
            order = b.order + 1
        stats.ocr_blocks += len(pg.paragraphs)

    # ---- metadata, link targets, independent sweep ---------------------------------------------------------
    for b in metadata_blocks(zf, name, settings, order):
        blocks.append(b)
        order = b.order + 1
    for b in hyperlink_blocks(zf, name, settings, order):
        blocks.append(b)
        order = b.order + 1
    corpus = norm(" \n ".join(b.text for b in blocks))
    sw = sweep(zf, "pptx", name, corpus, settings, order)
    blocks.extend(sw)
    stats.sweep_blocks = len(sw)
    if sw:
        warnings.append(f"{len(sw)} text unit(s) were found only by the XML completeness sweep (hidden/unsupported structures)")

    _c = [b.ocr_confidence for b in blocks if b.source == "ocr" and b.ocr_confidence is not None]
    stats.mean_ocr_confidence = round(sum(_c) / len(_c), 1) if _c else None
    stats.block_count = len(blocks)
    stats.ocr_chars = sum(len(b.text) for b in blocks if b.source == "ocr")
    stats.native_chars = sum(len(b.text) for b in blocks if b.source != "ocr")
    return ExtractedDocument(file_name=name, file_type="pptx", sha256=sha256_hex(data), size_bytes=len(data),
                             blocks=blocks, stats=stats, warnings=warnings, source_bytes=data)
