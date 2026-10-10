"""Rule 2 and 3 of CLAUDE.md: no raw PII in logs / reports, no network while processing."""

from __future__ import annotations

import logging
import socket

import pytest

from pii_shield import process_bytes
from pii_shield.reporting import audit_html, audit_json

from .conftest import FAST
from .fixtures import SYN_VALUES, docx_bytes, pdf_bytes, pptx_bytes


@pytest.mark.parametrize("maker,name", [(docx_bytes, "a.docx"), (pptx_bytes, "a.pptx"), (pdf_bytes, "a.pdf")])
def test_no_pii_in_logs_or_reports(maker, name: str, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    r = process_bytes(maker(), name, FAST)
    blobs = [caplog.text, audit_json(r), audit_html(r), " ".join(r.reasons), r.model_dump_json()]
    # model_dump_json includes the extracted document (the original text) by design; reports and logs must not
    for i, blob in enumerate(blobs[:4]):
        for v in SYN_VALUES:
            assert v not in blob, f"value of length {len(v)} found in output #{i}"


def test_no_network_during_processing(monkeypatch: pytest.MonkeyPatch) -> None:
    def deny(*a, **k):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    for maker, name in ((docx_bytes, "a.docx"), (pptx_bytes, "a.pptx"), (pdf_bytes, "a.pdf")):
        r = process_bytes(maker(), name, FAST)
        assert r.status.value != "BLOCKED", r.reasons


def _have_model() -> bool:
    try:
        import spacy

        spacy.load("en_core_web_lg", disable=["parser", "ner", "tagger", "lemmatizer", "attribute_ruler"])
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.slow
@pytest.mark.skipif(not _have_model(), reason="spaCy model not installed")
def test_no_network_with_ner(monkeypatch: pytest.MonkeyPatch) -> None:
    from pii_shield.settings import Settings

    def deny(*a, **k):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    r = process_bytes(docx_bytes(), "a.docx", Settings())
    assert r.status.value != "BLOCKED", r.reasons
