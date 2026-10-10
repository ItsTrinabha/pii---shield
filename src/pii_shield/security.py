"""Upload validation. The gateway processes attacker-controlled files, so this runs before any parser."""

from __future__ import annotations

import hashlib
import io
import posixpath
import re
import zipfile

from .errors import SecurityError, UnsupportedFileError
from .settings import Limits

_PDF_MAGIC = b"%PDF-"
_ZIP_MAGICS = (b"PK\x03\x04", b"PK\x05\x06")
_EXT_TO_TYPE = {".pdf": "pdf", ".pptx": "pptx", ".docx": "docx"}


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_name(name: str) -> str:
    """Strip any path and control characters. The name is used for display only, never for file access."""
    base = posixpath.basename(name.replace("\\", "/"))
    base = re.sub(r"[\x00-\x1f\x7f]", "", base)
    return base[:200] or "upload"


def sniff_type(data: bytes, filename: str) -> str:
    """Decide the real type from content, and reject if the extension lies."""
    ext = posixpath.splitext(filename.lower())[1]
    claimed = _EXT_TO_TYPE.get(ext)
    if claimed is None:
        raise UnsupportedFileError(f"extension {ext or '(none)'} is not supported (pdf, pptx, docx)")
    head = data[:8]
    if head.startswith(_PDF_MAGIC):
        actual = "pdf"
    elif head.startswith(_ZIP_MAGICS):
        actual = "ooxml"
    else:
        raise SecurityError("file content does not match any supported format (magic bytes)", "TYPE_CONFUSION")
    if claimed == "pdf" and actual != "pdf":
        raise SecurityError("extension says PDF but content is not a PDF", "TYPE_CONFUSION")
    if claimed in ("pptx", "docx") and actual != "ooxml":
        raise SecurityError(f"extension says {claimed.upper()} but content is not an OOXML package", "TYPE_CONFUSION")
    return claimed


def validate_zip_package(data: bytes, expected: str, limits: Limits) -> zipfile.ZipFile:
    """Open an OOXML package defensively: entry count, size, ratio, traversal, encryption, structure."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise SecurityError("corrupt or truncated ZIP container", "CORRUPT_FILE") from e
    infos = zf.infolist()
    if len(infos) > limits.max_zip_entries:
        raise SecurityError("too many entries in package", "ZIP_BOMB")
    total = 0
    for i in infos:
        name = i.filename
        norm = posixpath.normpath(name)
        if name.startswith(("/", "\\")) or norm.startswith("..") or "\\" in name or ".." in name.split("/"):
            raise SecurityError("path traversal entry in package", "PATH_TRAVERSAL")
        if i.flag_bits & 0x1:
            raise SecurityError("encrypted entry in package", "ENCRYPTED")
        total += i.file_size
        if total > limits.max_zip_uncompressed_bytes:
            raise SecurityError("package expands beyond the size limit", "ZIP_BOMB")
        if i.compress_size > 0 and i.file_size / max(i.compress_size, 1) > limits.max_zip_ratio and i.file_size > 1_000_000:
            raise SecurityError("suspicious compression ratio", "ZIP_BOMB")
    names = {i.filename for i in infos}
    if "[Content_Types].xml" not in names:
        raise SecurityError("not an OOXML package ([Content_Types].xml missing)", "TYPE_CONFUSION")
    marker = "word/document.xml" if expected == "docx" else "ppt/presentation.xml"
    if marker not in names:
        raise SecurityError(f"package is not a valid {expected.upper()} ({marker} missing)", "TYPE_CONFUSION")
    # Legacy encrypted OOXML is an OLE container, not a zip, so it fails the magic check above.
    return zf
