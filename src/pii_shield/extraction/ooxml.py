"""Shared OOXML helpers: safe XML parsing, metadata, hyperlink targets, completeness sweep, image OCR."""

from __future__ import annotations

import hashlib
import re
import zipfile
from collections.abc import Iterable

from lxml import etree

from ..errors import ExtractionError, SecurityError
from ..models import Block, Locator, WordBox
from ..settings import Settings
from .ocr import OcrPage, ocr_image_bytes_parallel
from .vector import render_vector_to_png

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "v": "urn:schemas-microsoft-com:vml",
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
}
W = "{%s}" % NS["w"]
A = "{%s}" % NS["a"]
MC = "{%s}" % NS["mc"]

_WS = re.compile(r"\s+")


def norm(s: str) -> str:
    return _WS.sub(" ", s).strip().lower()


_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False, dtd_validation=False)


def parse_xml(data: bytes, max_bytes: int) -> etree._Element:
    if len(data) > max_bytes:
        raise SecurityError("XML part exceeds size limit", "ZIP_BOMB")
    if b"<!ENTITY" in data or b"<!DOCTYPE" in data[:2048] and b"SYSTEM" in data[:4096]:
        raise SecurityError("XML entity / external DTD declaration rejected (XXE)", "XXE")
    try:
        return etree.fromstring(data, _PARSER)
    except etree.XMLSyntaxError as e:
        raise ExtractionError("malformed XML part", "CORRUPT_FILE") from e


def read_part(zf: zipfile.ZipFile, name: str, settings: Settings) -> bytes:
    info = zf.getinfo(name)
    if info.file_size > settings.limits.max_xml_part_bytes and name.endswith((".xml", ".rels")):
        raise SecurityError("XML part exceeds size limit", "ZIP_BOMB")
    with zf.open(info) as fh:
        data = fh.read(info.file_size + 1)
    if len(data) != info.file_size:
        raise SecurityError("ZIP entry size mismatch", "ZIP_BOMB")
    return data


# ---- text of a paragraph, text boxes handled separately ------------------------------------------------

def para_text(p: etree._Element, is_word: bool, include_deleted: bool = False) -> str:
    """Own text of a paragraph. Skips nested text boxes (handled as their own blocks) and AlternateContent fallbacks."""
    out: list[str] = []
    ns = W if is_word else A
    t_tag = ns + "t"
    del_tag = W + "delText"
    stack = [(p, False)]

    def walk(el):
        for ch in el:
            tag = ch.tag
            if not isinstance(tag, str):
                continue
            if tag == MC + "Fallback" or tag == W + "txbxContent":
                continue
            if tag == t_tag:
                out.append(ch.text or "")
            elif tag == del_tag and include_deleted:
                out.append(ch.text or "")
            elif tag in (W + "tab", A + "tab"):
                out.append("\t")
            elif tag in (W + "br", W + "cr", A + "br"):
                out.append("\n")
            elif tag == W + "noBreakHyphen":
                out.append("-")
            elif tag == W + "p" and ch is not p:
                continue  # nested paragraph (inside a text box content already skipped, or oddity)
            else:
                walk(ch)

    walk(p)
    del stack
    return "".join(out).replace("\v", "\n")


# ---- metadata and relationship targets -----------------------------------------------------------------

_META_PARTS = ("docProps/core.xml", "docProps/app.xml", "docProps/custom.xml")
_META_SKIP = {"TotalTime", "Words", "Characters", "Lines", "Paragraphs", "Slides", "Notes", "HiddenSlides", "MMClips",
              "ScaleCrop", "LinksUpToDate", "CharactersWithSpaces", "SharedDoc", "HyperlinksChanged", "AppVersion",
              "Pages", "Template", "DocSecurity", "TitlesOfParts", "HeadingPairs", "revision", "created", "modified",
              "lastPrinted", "Application", "PresentationFormat", "contentStatus", "language", "version"}


_NOISE = {"theme", "powerpoint presentation", "office theme", "slide titles", "en", "title", "headings"}


def _meta_noise(txt: str) -> bool:
    t = txt.strip()
    return t.isdigit() or t.startswith(("_Toc", "0x")) or t.lower() in _NOISE or len(t) < 2


def metadata_blocks(zf: zipfile.ZipFile, name: str, settings: Settings, start_order: int) -> list[Block]:
    blocks: list[Block] = []
    order = start_order
    for part in _META_PARTS:
        if part not in zf.namelist():
            continue
        root = parse_xml(read_part(zf, part, settings), settings.limits.max_xml_part_bytes)
        for el in root.iter():
            if not isinstance(el.tag, str):
                continue
            local = etree.QName(el).localname
            txt = (el.text or "").strip()
            if txt and len(list(el)) == 0 and local not in _META_SKIP and not _meta_noise(txt):
                loc = Locator(file=name, unit="metadata", part=local, block_id=f"meta-{part.split('/')[-1][:-4]}-{local}-{order}")
                blocks.append(Block(id=loc.block_id, text=txt, locator=loc, source="metadata", order=order))
                order += 1
    return blocks


def hyperlink_blocks(zf: zipfile.ZipFile, name: str, settings: Settings, start_order: int) -> list[Block]:
    """External relationship targets (mailto:, tel:, URLs) can carry personal data not visible in the text."""
    blocks: list[Block] = []
    order = start_order
    seen: set[str] = set()
    for part in zf.namelist():
        if not part.endswith(".rels"):
            continue
        root = parse_xml(read_part(zf, part, settings), settings.limits.max_xml_part_bytes)
        for rel in root:
            if rel.get("TargetMode") == "External":
                tgt = rel.get("Target") or ""
                if tgt and tgt not in seen and not tgt.startswith("file:"):
                    seen.add(tgt)
                    loc = Locator(file=name, unit="hyperlink", part="target", block_id=f"link-{order}")
                    blocks.append(Block(id=loc.block_id, text=tgt, locator=loc, source="metadata", order=order))
                    order += 1
    return blocks


# ---- completeness sweep ---------------------------------------------------------------------------------

_SWEEP_PREFIXES = {
    "docx": ("word/",),
    "pptx": ("ppt/",),
}
_ATTR_UNITS = ("descr", "title", "author", "initials")


def sweep_units(root: etree._Element, is_word: bool) -> Iterable[str]:
    pt = (W if is_word else A) + "p"
    for p in root.iter(pt):
        t = para_text(p, is_word, include_deleted=True)
        if t.strip():
            yield t
    for el in root.iter():
        tag = el.tag
        if not isinstance(tag, str):
            continue
        q = etree.QName(el)
        if q.localname in ("v", "text") and (el.text or "").strip() and q.namespace in (NS["c"], NS["p"]):
            yield el.text.strip()
        for an in _ATTR_UNITS:
            for key in (an, W + an):
                v = el.get(key)
                if v and v.strip() and not v.isdigit():
                    yield v.strip()
    # a:t that sit outside any a:p (charts)
    for t in root.iter(A + "t"):
        par = t.getparent()
        while par is not None and par.tag != A + "p":
            par = par.getparent()
        if par is None and (t.text or "").strip():
            yield t.text.strip()


def sweep(zf: zipfile.ZipFile, kind: str, name: str, corpus_norm: str, settings: Settings, start_order: int) -> list[Block]:
    """Every text-bearing XML part is scanned independently of python-pptx / python-docx.
    Anything not already present in the structured extraction becomes a residual block (fail-closed completeness)."""
    blocks: list[Block] = []
    order = start_order
    is_word = kind == "docx"
    seen: set[str] = set()
    prefixes = _SWEEP_PREFIXES[kind]
    for part in sorted(zf.namelist()):
        if not part.endswith(".xml") or not part.startswith(prefixes):
            continue
        if part.endswith(("presentation.xml", "theme1.xml", "styles.xml", "settings.xml", "fontTable.xml", "numbering.xml",
                          "webSettings.xml", "presProps.xml", "viewProps.xml", "tableStyles.xml", "stylesWithEffects.xml")):
            continue
        if "/theme/" in part or "/media/" in part:
            continue
        root = parse_xml(read_part(zf, part, settings), settings.limits.max_xml_part_bytes)
        for unit in sweep_units(root, is_word):
            n = norm(unit)
            if len(n) < 2 or n in corpus_norm or n in seen:
                continue
            seen.add(n)
            loc = Locator(file=name, unit="sweep", part=part, block_id=f"sweep-{order}")
            blocks.append(Block(id=loc.block_id, text=unit, locator=loc, source="sweep", order=order))
            order += 1
    return blocks


# ---- images ---------------------------------------------------------------------------------------------

_RASTER_EXT = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp")


def ocr_images(images: dict[str, bytes], settings: Settings) -> tuple[dict[str, OcrPage], list[str]]:
    """OCR raster images (and EMF/WMF via an optional renderer). Returns (results, unsupported_names)."""
    unsupported: list[str] = []
    jobs: list[tuple[str, bytes]] = []
    for key, data in images.items():
        low = key.lower()
        if low.endswith(_RASTER_EXT):
            jobs.append((key, data))
        elif low.endswith((".emf", ".wmf")):
            png = render_vector_to_png(data, low[low.rfind("."):], settings)
            if png:
                jobs.append((key, png))
            else:
                unsupported.append(key)
        else:
            unsupported.append(key)
    if len(jobs) > settings.limits.max_images_per_document:
        raise SecurityError("too many embedded images", "TOO_LARGE")
    results: dict[str, OcrPage] = {}
    for key, page, err in ocr_image_bytes_parallel(jobs, settings):
        if err or page is None:
            raise ExtractionError(f"OCR failed for embedded image {key} ({err})", err or "OCR_FAILED")
        results[key] = page
    return results, unsupported


def image_blocks(name: str, unit: str, index: int | None, key: str, page: OcrPage, start_order: int, dpi: int | None = None) -> list[Block]:
    out: list[Block] = []
    order = start_order
    for k, para in enumerate(page.paragraphs):
        loc = Locator(file=name, unit=unit, index=index, part=f"image:{key}", block_id=f"img-{hashlib.sha1(key.encode()).hexdigest()[:8]}-{k}-{order}")
        out.append(
            Block(
                id=loc.block_id, text=para.text, locator=loc, source="ocr", ocr_confidence=round(para.confidence, 1),
                order=order,
                geometry=[WordBox(start=s, end=e, x0=x0, y0=y0, x1=x1, y1=y1) for (s, e, x0, y0, x1, y1) in para.words],
            )
        )
        order += 1
    return out
