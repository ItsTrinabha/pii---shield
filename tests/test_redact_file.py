"""Redacted output files: raw values are gone, our own tokens do not trip the re-scan, and failure is closed."""

from __future__ import annotations

import io
import re
import zipfile

import pytest

from pii_shield import process_bytes
from pii_shield.errors import BlockedError
from pii_shield.models import Status
from pii_shield.redact import redact_file

from .conftest import FAST
from .fixtures import docx_bytes, pdf_bytes, pptx_bytes

LINES = ["Contact: Maria Fernandez, maria.fernandez@example.com, phone +1 415 555 0132.",
         "SSN 078-05-1120 belongs to the same person."]


def _text(data: bytes) -> str:
    z = zipfile.ZipFile(io.BytesIO(data))
    return " ".join(z.read(n).decode("utf8", "ignore") for n in z.namelist() if n.endswith(".xml"))


@pytest.mark.parametrize("make,name", [(docx_bytes, "a.docx"), (pptx_bytes, "a.pptx")])
def test_ooxml_redacted_file_has_no_raw_values(make, name) -> None:
    r = process_bytes(make(LINES), name, FAST)
    assert r.findings
    out = redact_file(r, approved_by="tester", settings=FAST)  # must not raise on its own tokens
    xml = _text(out)
    for raw in ("maria.fernandez@example.com", "078-05-1120"):
        assert raw not in xml
    assert re.search(r"\[EMAIL_\d+\]", xml)


def test_pdf_redacted_file_has_no_raw_values() -> None:
    import pymupdf

    r = process_bytes(pdf_bytes(LINES), "a.pdf", FAST)
    out = redact_file(r, approved_by="tester", settings=FAST)
    text = "".join(p.get_text() for p in pymupdf.open(stream=out, filetype="pdf"))
    assert "maria.fernandez@example.com" not in text and "078-05-1120" not in text


def test_review_needs_approval(monkeypatch) -> None:
    r = process_bytes(docx_bytes(LINES), "a.docx", FAST)
    r.status = Status.REVIEW
    with pytest.raises(BlockedError):
        redact_file(r, approved_by=None, settings=FAST)
