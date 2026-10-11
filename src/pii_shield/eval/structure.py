"""Structure-retention metric (definition: docs/METRICS.md).

The reference list of source units is built HERE, straight from the file, with its own XML walking. It deliberately does
not reuse the extractors (or python-docx / python-pptx), so an extraction bug cannot hide on both sides of the comparison.

A unit is retained when its text is found in an extracted block (found), that block's locator points at the right place
(locator), and the unit appears in source reading order relative to the other found units (order).
"""

from __future__ import annotations

import io
import re
import unicodedata
import zipfile
from bisect import bisect_left
from dataclasses import dataclass
from pathlib import PurePosixPath

from lxml import etree

from ..models import ExtractedDocument

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)


@dataclass
class Unit:
    kind: str  # paragraph | table-cell | header | footer | footnote | endnote | slide-text | slide-table | notes | page
    unit: str  # expected Locator.unit
    index: int | None  # expected Locator.index (slide/page) or None
    part: str  # expected Locator.part (exact for DOCX; a prefix such as "table:" for PPTX)
    text: str  # normalised text ("" for page units)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).replace("​", "").replace("­", "")
    return re.sub(r"\s+", " ", s).strip().lower()


def _xml(zf: zipfile.ZipFile, name: str) -> etree._Element:
    return etree.fromstring(zf.read(name), _PARSER)


def _own_text(p: etree._Element, ns: str) -> str:
    """Text of one paragraph: runs, tabs and breaks; skips nested text boxes and AlternateContent fallbacks."""
    out: list[str] = []

    def walk(el: etree._Element) -> None:
        for ch in el:
            if not isinstance(ch.tag, str) or ch.tag in (_MC + "Fallback", _W + "txbxContent"):
                continue
            if ch.tag == ns + "t":
                out.append(ch.text or "")
            elif ch.tag in (_W + "tab", _A + "tab", _W + "br", _W + "cr", _A + "br"):
                out.append(" ")
            elif ch.tag == _W + "noBreakHyphen":
                out.append("-")
            elif ch.tag not in (_W + "delText", _W + "instrText"):
                walk(ch)

    walk(p)
    return "".join(out)


# ---------------------------------------------------------------------------------------------------- DOCX
def _docx_container(el: etree._Element, unit: str, prefix: str, kind: str, out: list[Unit]) -> None:
    for ch in el:
        if ch.tag == _W + "p":
            t = _norm(_own_text(ch, _W))
            if t:
                out.append(Unit("table-cell" if "table r" in prefix else kind, unit, None, prefix, t))
            for tb in ch.iter(_W + "txbxContent"):
                if not any(a.tag == _MC + "Fallback" for a in tb.iterancestors()):
                    _docx_container(tb, unit, f"{prefix} textbox".strip(), kind, out)
        elif ch.tag == _W + "tbl":
            for ri, tr in enumerate(ch.iterfind(_W + "tr"), 1):
                for ci, tc in enumerate(tr.iterfind(_W + "tc"), 1):
                    _docx_container(tc, unit, f"{prefix} table r{ri}c{ci}".strip(), kind, out)
        elif ch.tag == _W + "sdt":
            content = ch.find(_W + "sdtContent")
            if content is not None:
                _docx_container(content, unit, prefix, kind, out)
        elif ch.tag in (_W + "ins", _W + "moveTo", _W + "customXml", _W + "smartTag"):
            _docx_container(ch, unit, prefix, kind, out)


def docx_units(data: bytes) -> list[Unit]:
    zf = zipfile.ZipFile(io.BytesIO(data))
    out: list[Unit] = []
    doc = _xml(zf, "word/document.xml")
    body = doc.find(_W + "body")
    if body is not None:
        _docx_container(body, "body", "", "paragraph", out)
    # headers/footers actually referenced by a section, each part once
    rels = {r.get("Id"): r.get("Target") for r in _xml(zf, "word/_rels/document.xml.rels").iter(_REL + "Relationship")}
    seen: set[str] = set()
    for ref in doc.iter(_W + "headerReference", _W + "footerReference"):
        target = rels.get(ref.get(_R + "id") or "")
        if not target or target in seen:
            continue
        seen.add(target)
        kind = "header" if ref.tag == _W + "headerReference" else "footer"
        hf: list[Unit] = []
        _docx_container(_xml(zf, f"word/{target}"), kind, "", kind, hf)
        out += [Unit(kind, kind, None, "", u.text) for u in hf]  # section label in the part is extractor-specific
    for name, tag in (("word/footnotes.xml", "footnote"), ("word/endnotes.xml", "endnote")):
        if name in zf.namelist():
            for el in _xml(zf, name).iter(_W + tag):
                if el.get(_W + "type") in ("separator", "continuationSeparator", "continuationNotice"):
                    continue
                for p in el.iter(_W + "p"):
                    t = _norm(_own_text(p, _W))
                    if t:
                        out.append(Unit(tag, tag, None, "", t))
    return out


# ---------------------------------------------------------------------------------------------------- PPTX
def _pptx_shapes(tree: etree._Element, slide: int | None, unit: str, out: list[Unit]) -> None:
    for el in tree:
        if el.tag == _P + "grpSp":
            _pptx_shapes(el, slide, unit, out)
        elif el.tag == _P + "sp":
            body = el.find(_P + "txBody")
            if body is not None:
                for p in body.iterfind(_A + "p"):
                    t = _norm(_own_text(p, _A))
                    if t:
                        out.append(Unit("slide-text", unit, slide, "shape:", t))
        elif el.tag == _P + "graphicFrame":
            for tc in el.iter(_A + "tc"):
                if tc.get("hMerge") == "1" or tc.get("vMerge") == "1":
                    continue
                for p in tc.iter(_A + "p"):
                    t = _norm(_own_text(p, _A))
                    if t:
                        out.append(Unit("slide-table", unit, slide, "table:", t))


def pptx_units(data: bytes) -> list[Unit]:
    zf = zipfile.ZipFile(io.BytesIO(data))
    pres = _xml(zf, "ppt/presentation.xml")
    rels = {r.get("Id"): r.get("Target") for r in _xml(zf, "ppt/_rels/presentation.xml.rels").iter(_REL + "Relationship")}
    out: list[Unit] = []
    for n, sid in enumerate(pres.iter(_P + "sldId"), 1):
        target = rels.get(sid.get(_R + "id") or "")
        if not target:
            continue
        path = str(PurePosixPath("ppt") / target)
        tree = _xml(zf, path).find(f"{_P}cSld/{_P}spTree")
        if tree is not None:
            _pptx_shapes(tree, n, "slide", out)
        # notes slide (body placeholder only; slide-number placeholders are not content)
        srels = f"{PurePosixPath(path).parent}/_rels/{PurePosixPath(path).name}.rels"
        if srels in zf.namelist():
            for r in _xml(zf, srels).iter(_REL + "Relationship"):
                if r.get("Type", "").endswith("/notesSlide"):
                    npath = re.sub(r"[^/]+/\.\./", "", str(PurePosixPath(path).parent / r.get("Target", "")))
                    if npath not in zf.namelist():
                        continue
                    for sp in _xml(zf, npath).iter(_P + "sp"):
                        ph = sp.find(f"{_P}nvSpPr/{_P}nvPr/{_P}ph")
                        if ph is None or ph.get("type") != "body":
                            continue
                        body = sp.find(_P + "txBody")
                        text = _norm(" ".join(_own_text(p, _A) for p in body.iterfind(_A + "p"))) if body is not None else ""
                        if text:
                            out.append(Unit("notes", "slide", n, "notes", text))
    return out


# ---------------------------------------------------------------------------------------------------- PDF
def pdf_units(data: bytes) -> list[Unit]:
    """Scanned or native, a PDF has no reliable logical structure to compare against: units are pages that carry ink."""
    import numpy as np
    import pymupdf

    out: list[Unit] = []
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        for i, page in enumerate(doc, 1):
            pix = page.get_pixmap(dpi=36, colorspace=pymupdf.csGRAY)
            dark = int(np.count_nonzero(np.frombuffer(pix.samples, dtype=np.uint8) < 160))
            if dark > 30:  # a blank page carries only its running header/footer at most
                out.append(Unit("page", "page", i, "", ""))
    return out


# ---------------------------------------------------------------------------------------------------- scoring
def _locator_ok(u: Unit, loc) -> bool:
    if u.unit != loc.unit or (u.index is not None and u.index != loc.index):
        return False
    if u.kind in ("paragraph", "table-cell", "footnote", "endnote"):
        return loc.part == u.part
    if u.kind in ("slide-text", "slide-table"):
        return loc.part.startswith(u.part)
    if u.kind == "notes":
        return loc.part == "notes"
    return True  # header/footer: unit is enough (section labels are extractor-specific); page: unit+index


def _lis_members(seq: list[int]) -> set[int]:
    """Indices (into seq) of one longest strictly increasing subsequence."""
    tails: list[int] = []
    tails_idx: list[int] = []
    prev = [-1] * len(seq)
    for i, v in enumerate(seq):
        k = bisect_left(tails, v)
        if k == len(tails):
            tails.append(v)
            tails_idx.append(i)
        else:
            tails[k] = v
            tails_idx[k] = i
        prev[i] = tails_idx[k - 1] if k else -1
    out: set[int] = set()
    i = tails_idx[-1] if tails_idx else -1
    while i != -1:
        out.add(i)
        i = prev[i]
    return out


def score(units: list[Unit], doc: ExtractedDocument) -> dict:
    blocks = [(i, b, _norm(b.text)) for i, b in enumerate(doc.blocks) if b.source != "sweep"]
    found: list[tuple[Unit, int, bool]] = []  # (unit, block position, locator ok)
    last = -1
    for u in units:
        if u.kind == "page":
            cands = [i for i, b, _ in blocks if b.locator.unit == "page" and b.locator.index == u.index]
        else:
            # exact block matches first: short cells ("r", "a" in a RACI grid) are substrings of unrelated blocks
            cands = [i for i, b, t in blocks if t == u.text] or [i for i, b, t in blocks if u.text in t]
        if not cands:
            continue
        # prefer a block with the right locator, then the first one at or after the previous match (reading order)
        good = [i for i in cands if _locator_ok(u, doc.blocks[i].locator)] or cands
        after = [i for i in good if i >= last]
        pos = after[0] if after else good[0]
        last = max(last, pos)
        found.append((u, pos, _locator_ok(u, doc.blocks[pos].locator)))
    in_order = _lis_members([p for _, p, _ in found])
    n = len(units)
    nf = len(found)
    nloc = sum(1 for _, _, ok in found if ok)
    nord = len(in_order)
    retained = sum(1 for k, (_, _, ok) in enumerate(found) if ok and k in in_order)
    by_kind: dict[str, dict[str, int]] = {}
    for u in units:
        by_kind.setdefault(u.kind, {"units": 0, "retained": 0})["units"] += 1
    for k, (u, _, ok) in enumerate(found):
        if ok and k in in_order:
            by_kind[u.kind]["retained"] += 1
    return {
        "units": n, "found": nf, "locator_ok": nloc, "in_order": nord, "retained": retained,
        "found_rate": nf / n if n else None, "locator_rate": nloc / nf if nf else None,
        "order_rate": nord / nf if nf else None, "retention": retained / n if n else None,
        "unit_level": "page" if units and units[0].kind == "page" else "paragraph/cell",
        "by_kind": by_kind,
    }


def reference_units(data: bytes, file_name: str) -> list[Unit]:
    ext = file_name.lower().rsplit(".", 1)[-1]
    if ext == "docx":
        return docx_units(data)
    if ext == "pptx":
        return pptx_units(data)
    if ext == "pdf":
        return pdf_units(data)
    raise ValueError(f"no structure reference for .{ext}")


def structure_retention(data: bytes, file_name: str, doc: ExtractedDocument | None) -> dict | None:
    if doc is None:
        return None
    return score(reference_units(data, file_name), doc)
