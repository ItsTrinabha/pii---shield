"""Hostile and broken uploads must end BLOCKED with a reason code, never raise and never pass."""

from __future__ import annotations

import pytest

from pii_shield import process_bytes
from pii_shield.models import Status
from pii_shield.settings import Limits, Settings

from .conftest import FAST
from .fixtures import docx_bytes, pdf_bytes, pptx_bytes, rezip

XXE_DOC = (b'<?xml version="1.0"?><!DOCTYPE w [<!ENTITY x SYSTEM "file:///etc/hostname">]>'
           b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           b'<w:body><w:p><w:r><w:t>&x;</w:t></w:r></w:p></w:body></w:document>')


def _blocked(data: bytes, name: str, settings: Settings = FAST) -> str:
    r = process_bytes(data, name, settings)
    assert r.status == Status.BLOCKED, (name, r.reasons)
    assert r.reasons and not r.sanitized_blocks
    return " ".join(r.reasons)


def test_empty_file() -> None:
    assert "EMPTY" in _blocked(b"", "a.pdf")


@pytest.mark.parametrize("name", ["a.exe", "a.txt", "noext", "a.doc"])
def test_unsupported_extension(name: str) -> None:
    assert "UNSUPPORTED" in _blocked(b"%PDF-1.7 x", name)


def test_pdf_named_as_docx() -> None:
    assert "TYPE_CONFUSION" in _blocked(pdf_bytes(), "a.docx")


def test_docx_named_as_pdf() -> None:
    assert "TYPE_CONFUSION" in _blocked(docx_bytes(), "a.pdf")


def test_docx_named_as_pptx() -> None:
    assert "TYPE_CONFUSION" in _blocked(docx_bytes(), "a.pptx")


def test_random_bytes() -> None:
    assert "TYPE_CONFUSION" in _blocked(b"\x00\x01garbage" * 50, "a.pdf")


def test_truncated_docx() -> None:
    _blocked(docx_bytes()[:400], "a.docx")


def test_corrupt_pdf() -> None:
    _blocked(b"%PDF-1.7\n" + b"\x00" * 300, "a.pdf")


def test_encrypted_pdf() -> None:
    assert "ENCRYPTED" in _blocked(pdf_bytes(encrypt=True), "a.pdf")


def test_encrypted_zip_entry() -> None:
    assert "ENCRYPTED" in _blocked(rezip(docx_bytes(), encrypted_flag="word/document.xml"), "a.docx")


def test_zip_bomb_ratio() -> None:
    bomb = rezip(docx_bytes(), add={"word/media/pad.bin": b"\x00" * 3_000_000})
    assert "ZIP_BOMB" in _blocked(bomb, "a.docx")


def test_zip_bomb_total_size() -> None:
    tiny = Settings(use_ner=False, limits=Limits(max_zip_uncompressed_bytes=10_000))
    assert "ZIP_BOMB" in _blocked(docx_bytes(), "a.docx", tiny)


def test_too_many_entries() -> None:
    tiny = Settings(use_ner=False, limits=Limits(max_zip_entries=5))
    assert "ZIP_BOMB" in _blocked(docx_bytes(), "a.docx", tiny)


@pytest.mark.parametrize("entry", ["../evil.xml", "word/../../evil.xml", "/abs.xml"])
def test_path_traversal(entry: str) -> None:
    assert "PATH_TRAVERSAL" in _blocked(rezip(docx_bytes(), add={entry: b"<x/>"}), "a.docx")


def test_upload_too_large() -> None:
    tiny = Settings(use_ner=False, limits=Limits(max_upload_bytes=1000))
    assert "TOO_LARGE" in _blocked(docx_bytes(), "a.docx", tiny)


def test_xxe_rejected_and_not_resolved() -> None:
    data = rezip(docx_bytes(), replace={"word/document.xml": XXE_DOC})
    r = process_bytes(data, "a.docx", FAST)
    assert r.status == Status.BLOCKED
    assert all("etc" not in b.text for b in r.sanitized_blocks)


def test_missing_main_part() -> None:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
    assert "TYPE_CONFUSION" in _blocked(buf.getvalue(), "a.pptx")


def test_hostile_filename_is_neutralised() -> None:
    r = process_bytes(docx_bytes(), "..\\..\\evil\x00\x07.docx", FAST)
    assert r.document is not None
    assert "/" not in r.document.file_name and "\\" not in r.document.file_name and "\x00" not in r.document.file_name


@pytest.mark.parametrize("maker,name", [(docx_bytes, "ok.docx"), (pptx_bytes, "ok.pptx"), (pdf_bytes, "ok.pdf")])
def test_valid_synthetic_files_are_processed(maker, name: str) -> None:
    r = process_bytes(maker(), name, FAST)
    assert r.status != Status.BLOCKED, r.reasons
    assert r.findings
