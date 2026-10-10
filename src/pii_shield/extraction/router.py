"""Entry point for extraction: validate, sniff the real type, dispatch."""

from __future__ import annotations

from ..errors import ExtractionError, SecurityError
from ..models import ExtractedDocument
from ..security import safe_name, sniff_type
from ..settings import Settings
from .docx import extract_docx
from .pdf import extract_pdf
from .pptx import extract_pptx


def extract(data: bytes, file_name: str, settings: Settings | None = None) -> ExtractedDocument:
    settings = settings or Settings()
    if not data:
        raise ExtractionError("empty file", "EMPTY_DOCUMENT")
    if len(data) > settings.limits.max_upload_bytes:
        raise SecurityError("file exceeds the upload size limit", "TOO_LARGE")
    name = safe_name(file_name)
    kind = sniff_type(data, name)
    if kind == "pdf":
        return extract_pdf(data, name, settings)
    if kind == "pptx":
        return extract_pptx(data, name, settings)
    return extract_docx(data, name, settings)
