"""OCR-vs-native support: render an Office file to PDF with a local LibreOffice, then rasterise every page into an
image-only PDF so the pipeline has to OCR it, exactly like a scan. Local only: no network, throwaway LibreOffice profile."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from ..extraction.vector import _soffice


def office_to_pdf(path: Path, timeout_s: int = 300) -> bytes:
    exe = _soffice()
    if not exe:
        raise RuntimeError("LibreOffice (soffice) not found; it is required for --render-ocr")
    with tempfile.TemporaryDirectory(prefix="pii_shield_render_") as td, tempfile.TemporaryDirectory(prefix="pii_shield_lo_") as prof:
        subprocess.run(
            [exe, f"-env:UserInstallation={Path(prof).as_uri()}", "--headless", "--convert-to", "pdf", "--outdir", td, str(path)],
            capture_output=True, timeout=timeout_s, check=False,
        )
        out = Path(td) / (path.stem + ".pdf")
        if not out.exists():
            raise RuntimeError(f"LibreOffice did not produce a PDF for {path.name}")
        return out.read_bytes()


def rasterise_pdf(pdf: bytes, dpi: int = 200) -> bytes:
    """Every page becomes a single image with no text layer, like a scanner output."""
    import pymupdf

    src = pymupdf.open(stream=pdf, filetype="pdf")
    dst = pymupdf.open()
    try:
        for page in src:
            pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB, alpha=False)
            out = dst.new_page(width=page.rect.width, height=page.rect.height)
            out.insert_image(out.rect, pixmap=pix)
        dst.set_metadata({})
        return dst.tobytes(deflate=True)
    finally:
        src.close()
        dst.close()


def ocr_variant(path: Path, dpi: int = 200) -> tuple[bytes, str]:
    """(image-only PDF bytes, file name for the pipeline) for a PPTX/DOCX/PDF sample."""
    pdf = path.read_bytes() if path.suffix.lower() == ".pdf" else office_to_pdf(path)
    return rasterise_pdf(pdf, dpi), f"{path.name}.ocr.pdf"
