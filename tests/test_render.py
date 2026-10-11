"""OCR-vs-native rendering: the rasterised PDF must carry no text layer, so the pipeline has to OCR it."""

from __future__ import annotations

import pymupdf
import pytest

from pii_shield.eval.render import office_to_pdf, rasterise_pdf
from pii_shield.extraction.vector import have_renderer

from .fixtures import docx_bytes, pdf_bytes


def test_rasterised_pdf_has_no_text_layer() -> None:
    src = pdf_bytes()
    out = rasterise_pdf(src, dpi=100)
    with pymupdf.open(stream=src, filetype="pdf") as a, pymupdf.open(stream=out, filetype="pdf") as b:
        assert a.page_count == b.page_count
        assert a[0].get_text().strip()
        assert not any(p.get_text().strip() for p in b)
        assert b[0].get_images()
        assert not b.metadata.get("author") and not b.metadata.get("title")


@pytest.mark.slow
@pytest.mark.skipif(not have_renderer(), reason="LibreOffice not installed")
def test_office_to_pdf_renders_docx(tmp_path) -> None:
    p = tmp_path / "s.docx"
    p.write_bytes(docx_bytes())
    pdf = office_to_pdf(p)
    with pymupdf.open(stream=pdf, filetype="pdf") as d:
        assert d.page_count >= 1 and d[0].get_text().strip()
