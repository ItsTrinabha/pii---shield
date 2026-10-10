"""Runtime configuration. Defaults are conservative (privacy-first)."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from importlib import resources


@dataclass(frozen=True)
class Limits:
    max_upload_bytes: int = 100 * 1024 * 1024
    max_pdf_pages: int = 400
    max_zip_entries: int = 5000
    max_zip_uncompressed_bytes: int = 600 * 1024 * 1024
    max_zip_ratio: float = 200.0  # per-entry uncompressed/compressed
    max_xml_part_bytes: int = 64 * 1024 * 1024
    max_image_pixels: int = 60_000_000
    max_images_per_document: int = 400
    ocr_timeout_s: int = 120
    max_total_seconds: int = 1800


@dataclass(frozen=True)
class Settings:
    # detection
    mask_threshold: float = 0.45  # findings below this are logged but not masked (never for hard types)
    review_band: float = 0.30  # findings between review_band and mask_threshold -> REVIEW
    ner_model: str = "en_core_web_lg"
    use_ner: bool = True
    # OCR
    ocr_dpi: int = 250
    ocr_lang: str = "eng"
    min_native_chars_for_text_page: int = 40
    low_ocr_confidence: float = 60.0  # page mean word confidence below this => REVIEW
    min_ink_coverage: float = 0.45  # fraction of ink inside OCR word boxes below this => REVIEW
    ocr_workers: int = max(1, min(4, os.cpu_count() or 1))
    # verification
    strict_verifier: bool = False  # True: soft hits also BLOCK
    # misc
    limits: Limits = field(default_factory=Limits)

    def digest(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True, default=str).encode()).hexdigest()[:16]


@lru_cache(maxsize=1)
def allowlist() -> dict:
    with resources.files("pii_shield.config").joinpath("allowlist.json").open("r", encoding="utf-8") as fh:
        return json.load(fh)
