"""OCR utilities (Tesseract). Returns paragraph blocks with word boxes so findings can be burned into images."""

from __future__ import annotations

import io
import os
import shutil
import threading
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field

import cv2
import numpy as np
import pytesseract
from PIL import Image, ImageOps

from ..errors import OcrError, SecurityError
from ..settings import Settings

os.environ.setdefault("OMP_THREAD_LIMIT", "1")  # one core per Tesseract process; we parallelise across processes


def find_tesseract() -> str | None:
    """PII_SHIELD_TESSERACT, then PATH, then the default Windows installer locations (which skip PATH)."""
    cands = [os.environ.get("PII_SHIELD_TESSERACT"), shutil.which("tesseract")]
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"), os.environ.get("LOCALAPPDATA")):
        if base:
            cands.append(os.path.join(base, "Tesseract-OCR", "tesseract.exe"))
            cands.append(os.path.join(base, "Programs", "Tesseract-OCR", "tesseract.exe"))
    return next((c for c in cands if c and os.path.isfile(c)), None)


_TESS = find_tesseract()
if _TESS:
    pytesseract.pytesseract.tesseract_cmd = _TESS


@dataclass
class OcrParagraph:
    text: str
    words: list[tuple[int, int, int, int, int, int]]  # (start, end, x0, y0, x1, y1) in source-image pixels
    confidence: float
    bbox: tuple[int, int, int, int]


@dataclass
class OcrPage:
    paragraphs: list[OcrParagraph] = field(default_factory=list)
    mean_confidence: float | None = None
    ink_coverage: float | None = None
    width: int = 0
    height: int = 0
    char_count: int = 0


def load_image(data: bytes, max_pixels: int) -> np.ndarray:
    """Decode untrusted image bytes defensively into a BGR uint8 array."""
    try:
        with Image.open(io.BytesIO(data)) as im:
            w, h = im.size
            if w * h > max_pixels:
                raise SecurityError("image exceeds pixel limit (decompression bomb)", "IMAGE_BOMB")
            im = ImageOps.exif_transpose(im)
            if im.mode in ("RGBA", "LA", "P"):
                im = im.convert("RGBA")
                bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
                bg.alpha_composite(im)
                im = bg
            im = im.convert("RGB")
            arr = np.asarray(im)
    except SecurityError:
        raise
    except Exception as e:  # noqa: BLE001
        raise OcrError("image could not be decoded") from e
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def _prep(gray: np.ndarray) -> tuple[np.ndarray, float]:
    """Upscale small images (UI screenshots) so Tesseract sees >= ~1800px width."""
    h, w = gray.shape[:2]
    scale = 1.0
    if w < 1500:
        scale = min(3.0, 1800.0 / max(w, 1))
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    return gray, scale


def ocr_array(bgr: np.ndarray, settings: Settings) -> OcrPage:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    h0, w0 = gray.shape[:2]
    page = OcrPage(width=w0, height=h0)
    if h0 < 12 or w0 < 12:
        return page
    # Dark-background screenshots: invert so text is dark on light
    if float(np.mean(gray)) < 90:
        gray = cv2.bitwise_not(gray)
    g, scale = _prep(gray)
    try:
        d = pytesseract.image_to_data(
            g,
            lang=settings.ocr_lang,
            config="--oem 1 --psm 3 -c preserve_interword_spaces=1",
            output_type=pytesseract.Output.DICT,
            timeout=settings.limits.ocr_timeout_s,
        )
    except RuntimeError as e:  # tesseract timeout
        raise OcrError("OCR timed out") from e
    except pytesseract.TesseractError as e:
        raise OcrError("OCR engine error") from e

    n = len(d["text"])
    groups: dict[tuple[int, int], dict[int, list[int]]] = {}
    for i in range(n):
        txt = (d["text"][i] or "").strip()
        if not txt:
            continue
        key = (d["block_num"][i], d["par_num"][i])
        groups.setdefault(key, {}).setdefault(d["line_num"][i], []).append(i)

    all_conf: list[float] = []
    for key in sorted(groups.keys()):
        lines = groups[key]
        text_parts: list[str] = []
        words: list[tuple[int, int, int, int, int, int]] = []
        confs: list[float] = []
        pos = 0
        xs0, ys0, xs1, ys1 = [], [], [], []
        for ln in sorted(lines.keys()):
            idxs = sorted(lines[ln], key=lambda j: d["left"][j])
            line_text = ""
            for j in idxs:
                w = d["text"][j].strip()
                if line_text:
                    line_text += " "
                s = pos + len(line_text)
                line_text += w
                e = pos + len(line_text)
                x0 = int(d["left"][j] / scale)
                y0 = int(d["top"][j] / scale)
                x1 = int((d["left"][j] + d["width"][j]) / scale)
                y1 = int((d["top"][j] + d["height"][j]) / scale)
                words.append((s, e, x0, y0, x1, y1))
                xs0.append(x0), ys0.append(y0), xs1.append(x1), ys1.append(y1)
                c = float(d["conf"][j])
                if c >= 0:
                    confs.append(c)
                    all_conf.append(c)
            text_parts.append(line_text)
            pos += len(line_text) + 1  # newline
        text = "\n".join(text_parts)
        if text.strip():
            page.paragraphs.append(
                OcrParagraph(
                    text=text,
                    words=words,
                    confidence=float(np.mean(confs)) if confs else 0.0,
                    bbox=(min(xs0), min(ys0), max(xs1), max(ys1)),
                )
            )
            page.char_count += len(text)
    page.mean_confidence = float(np.mean(all_conf)) if all_conf else None
    try:
        _recover_missed(gray, page, settings)
    except Exception:  # noqa: BLE001 - recovery is best-effort; the coverage metric still reports the gap
        pass
    page.ink_coverage = _ink_coverage(gray, page)
    return page


def _glyph_ink(gray: np.ndarray) -> np.ndarray:
    """Mask of glyph-like thin strokes, dark-on-light and light-on-dark. Large fills and long rules are dropped,
    so table header bands and borders do not count as 'missed text'."""
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
    thin = cv2.max(cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, k), cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, k))
    _, m = cv2.threshold(thin, 40, 255, cv2.THRESH_BINARY)
    n, labels, st, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    keep = np.zeros(n, dtype=bool)
    h, w = st[:, cv2.CC_STAT_HEIGHT], st[:, cv2.CC_STAT_WIDTH]
    keep[1:] = (h[1:] >= 4) & (h[1:] <= 90) & (w[1:] <= 160) & (w[1:] / np.maximum(h[1:], 1) < 14)
    return keep[labels].astype(np.uint8) * 255



def _recover_missed(gray: np.ndarray, page: OcrPage, settings: Settings, max_regions: int = 80) -> None:
    """Second pass over glyph-like ink the page-level OCR ignored (white-on-navy table headers, coloured chips,
    stamps). Each region is cropped, polarity-normalised, upscaled and read as a single line."""
    ink = _glyph_ink(gray)
    mask = np.zeros_like(ink)
    for p in page.paragraphs:
        for (_, _, x0, y0, x1, y1) in p.words:
            cv2.rectangle(mask, (max(x0 - 5, 0), max(y0 - 5, 0)), (x1 + 5, y1 + 5), 255, -1)
    unc = cv2.bitwise_and(ink, cv2.bitwise_not(mask))
    if np.count_nonzero(unc) < 150:
        return
    merged = cv2.dilate(unc, cv2.getStructuringElement(cv2.MORPH_RECT, (31, 11)))
    cnts, _ = cv2.findContours(merged, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = sorted((cv2.boundingRect(c) for c in cnts), key=lambda b: (b[1] // 20, b[0]))
    H, W = gray.shape[:2]
    added = 0
    for (x, y, w, h) in boxes:
        if added >= max_regions:
            break
        if w < 18 or h < 9 or h > 90 or w > W * 0.9:
            continue
        if np.count_nonzero(unc[y:y + h, x:x + w]) < 40:
            continue
        pad = 10
        x0, y0, x1, y1 = max(x - pad, 0), max(y - pad, 0), min(x + w + pad, W), min(y + h + pad, H)
        crop = gray[y0:y1, x0:x1]
        if float(np.mean(crop)) < 128:
            crop = cv2.bitwise_not(crop)
        sc = max(1.0, 70.0 / max(crop.shape[0], 1))
        crop = cv2.resize(crop, None, fx=sc, fy=sc, interpolation=cv2.INTER_CUBIC)
        crop = cv2.copyMakeBorder(crop, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=255)
        try:
            d = pytesseract.image_to_data(crop, lang=settings.ocr_lang, config="--oem 1 --psm 7",
                                          output_type=pytesseract.Output.DICT, timeout=30)
        except Exception:  # noqa: BLE001
            continue
        words, confs = [], []
        for i, t in enumerate(d["text"]):
            t = (t or "").strip()
            if t and float(d["conf"][i]) >= 60 and sum(ch.isalnum() for ch in t) >= 1:
                words.append(t)
                confs.append(float(d["conf"][i]))
        text = " ".join(words)
        if sum(ch.isalnum() for ch in text) < 2:
            continue
        # one word box spanning the region so burn-in redaction can still cover it
        page.paragraphs.append(OcrParagraph(text=text, words=[(0, len(text), x0, y0, x1, y1)],
                                            confidence=float(np.mean(confs)), bbox=(x0, y0, x1, y1)))
        page.char_count += len(text)
        added += 1


def _ink_coverage(gray: np.ndarray, page: OcrPage) -> float | None:
    """Independent completeness signal: share of glyph-like ink that lies inside recognised word boxes.

    Low values mean ink exists that OCR did not turn into text (missed text, stamps, handwriting, diagrams)."""
    try:
        ink = _glyph_ink(gray)
        total = int(np.count_nonzero(ink))
        if total < 200:
            return 1.0
        mask = np.zeros_like(ink)
        pad = 5
        for p in page.paragraphs:
            for (_, _, x0, y0, x1, y1) in p.words:
                cv2.rectangle(mask, (max(x0 - pad, 0), max(y0 - pad, 0)), (x1 + pad, y1 + pad), 255, -1)
        covered = int(np.count_nonzero(cv2.bitwise_and(ink, mask)))
        return covered / total
    except Exception:  # noqa: BLE001
        return None


# ---- parallel drivers (threads: each OCR call is its own Tesseract subprocess, so no GIL contention) -----------


def _safe(fn, *a):
    try:
        return fn(*a), None
    except Exception as e:  # noqa: BLE001
        return None, getattr(e, "code", "OCR_FAILED")


def ocr_pdf_pages(pdf_bytes: bytes, indices: list[int], settings: Settings) -> list[tuple[int, OcrPage | None, str | None]]:
    """Render in this thread (PyMuPDF is not thread-safe), OCR in a bounded thread pool."""
    import pymupdf

    if not indices:
        return []
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    out: dict[int, tuple[OcrPage | None, str | None]] = {}
    inflight: deque[tuple[int, Future]] = deque()
    workers = max(1, settings.ocr_workers)
    try:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for i in indices:
                pix = doc[i].get_pixmap(dpi=settings.ocr_dpi, colorspace=pymupdf.csRGB, alpha=False)
                arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
                bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
                inflight.append((i, ex.submit(_safe, ocr_array, bgr, settings)))
                while len(inflight) >= workers * 2:  # bound memory: at most 2 rendered pages per worker
                    j, fut = inflight.popleft()
                    out[j] = fut.result()
            while inflight:
                j, fut = inflight.popleft()
                out[j] = fut.result()
    finally:
        doc.close()
    return [(i, *out[i]) for i in indices]


def ocr_image_bytes_parallel(jobs: list[tuple[str, bytes]], settings: Settings) -> list[tuple[str, OcrPage | None, str | None]]:
    def one(key: str, data: bytes):
        def run():
            return ocr_array(load_image(data, settings.limits.max_image_pixels), settings)

        res, err = _safe(run)
        return key, res, err

    if not jobs:
        return []
    with ThreadPoolExecutor(max_workers=max(1, settings.ocr_workers)) as ex:
        return list(ex.map(lambda kv: one(*kv), jobs))
