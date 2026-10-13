"""Core data models. Nothing in here stores raw PII values outside Block.text."""

from __future__ import annotations

import enum
import hashlib
import hmac
import json
import os
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Status(str, enum.Enum):
    PASS = "PASS"  # sanitised and verified: may go downstream
    REVIEW = "REVIEW"  # soft signals remain: a human must approve before release
    BLOCKED = "BLOCKED"  # extraction failed, or hard residual PII: never released


class EntityType(str, enum.Enum):
    PERSON = "PERSON"
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    EMPLOYEE_ID = "EMPLOYEE_ID"
    SSN = "SSN"
    PASSPORT = "PASSPORT"
    TAX_ID = "TAX_ID"
    DATE_OF_BIRTH = "DATE_OF_BIRTH"
    ADDRESS = "ADDRESS"
    FINANCIAL_ACCOUNT = "FINANCIAL_ACCOUNT"
    IP_ADDRESS = "IP_ADDRESS"
    GOV_ID = "GOV_ID"
    TECH_ID = "TECH_ID"
    SECRET = "SECRET"
    GENERIC_ID = "GENERIC_ID"


# Human-readable classification used in the audit report.
CLASSIFICATION: dict[str, tuple[str, str]] = {
    "PERSON": ("Direct identifier", "Full name"),
    "EMAIL": ("Contact detail", "Email address"),
    "PHONE": ("Contact detail", "Telephone number"),
    "EMPLOYEE_ID": ("Employee identifier", "Staff / director number"),
    "SSN": ("Government-issued ID", "Social security number (full or last digits)"),
    "PASSPORT": ("Government-issued ID", "Passport number"),
    "TAX_ID": ("Government-issued ID", "National tax identifier (PAN-style)"),
    "DATE_OF_BIRTH": ("Sensitive attribute", "Date of birth"),
    "ADDRESS": ("Contact detail", "Residential / postal address"),
    "FINANCIAL_ACCOUNT": ("Financial identifier", "Card / account number or fragment"),
    "IP_ADDRESS": ("Technical identifier", "IP address"),
    "GOV_ID": ("Government-issued ID", "National ID (Aadhaar, UK NINO, Canadian SIN)"),
    "TECH_ID": ("Technical identifier", "Device / vehicle identifier (MAC, VIN, registration plate)"),
    "SECRET": ("Credential / secret", "API key, token, password or private key"),
    "GENERIC_ID": ("Other identifier", "Unrecognised reference / record number (PREFIX-...-digits)"),
}


class Locator(BaseModel):
    model_config = ConfigDict(frozen=True)

    file: str
    unit: str  # "page" | "slide" | "body" | "header" | "footer" | "metadata" | ...
    index: int | None = None  # page / slide number (1-based) when applicable
    part: str = ""  # e.g. "table r2c3", "notes", "image:word/media/image4.png"
    block_id: str = ""

    def label(self) -> str:
        base = self.unit if self.index is None else f"{self.unit} {self.index}"
        return f"{base} / {self.part}" if self.part else base


class WordBox(BaseModel):
    """Character span [start, end) of a block mapped to a pixel box on a rendered page."""

    start: int
    end: int
    x0: int
    y0: int
    x1: int
    y1: int


class Block(BaseModel):
    id: str
    text: str
    locator: Locator
    source: str = "native"  # native | ocr | metadata | sweep
    ocr_confidence: float | None = None  # mean word confidence 0..100
    order: int = 0
    geometry: list[WordBox] = Field(default_factory=list, exclude=True, repr=False)
    render_dpi: int | None = Field(default=None, exclude=True)


class DocStats(BaseModel):
    page_count: int = 0
    block_count: int = 0
    ocr_blocks: int = 0
    ocr_pages: int = 0
    native_chars: int = 0
    ocr_chars: int = 0
    mean_ocr_confidence: float | None = None
    low_confidence_pages: list[int] = Field(default_factory=list)
    ink_coverage: dict[int, float] = Field(default_factory=dict)  # page -> fraction of ink inside OCR boxes
    sweep_blocks: int = 0
    unsupported_media: list[str] = Field(default_factory=list)
    hidden_content_blocks: int = 0


class ExtractedDocument(BaseModel):
    file_name: str
    file_type: str  # pdf | pptx | docx
    sha256: str
    size_bytes: int
    blocks: list[Block]
    stats: DocStats = Field(default_factory=DocStats)
    warnings: list[str] = Field(default_factory=list)
    # kept out of serialisation: needed only for visual redaction of scanned PDFs
    source_bytes: bytes | None = Field(default=None, exclude=True, repr=False)


class Finding(BaseModel):
    """A detected PII span. Deliberately carries NO raw value (only offsets and a keyed fingerprint)."""

    id: str
    type: str
    block_id: str
    start: int
    end: int
    confidence: float
    detectors: list[str]
    locator: Locator
    token: str = ""
    action: str = "MASKED"
    fingerprint: str = ""  # HMAC of normalised value: joinable in audit, not reversible without key
    length: int = 0
    ocr_derived: bool = False
    note: str = ""


class VerificationHit(BaseModel):
    severity: str  # HARD | SOFT
    rule: str
    block_id: str
    locator: Locator
    start: int
    end: int


class Verification(BaseModel):
    passed: bool
    hard_hits: list[VerificationHit] = Field(default_factory=list)
    soft_hits: list[VerificationHit] = Field(default_factory=list)
    rules_run: list[str] = Field(default_factory=list)


class SanitizedBlock(BaseModel):
    id: str
    locator: Locator
    text: str


_SEAL_KEY = os.urandom(32)  # per process: a seal cannot be forged from outside this process or replayed across runs


def compute_seal(document: str, blocks: tuple[SanitizedBlock, ...], approved_by: str | None) -> str:
    h = hmac.new(_SEAL_KEY, digestmod=hashlib.sha256)
    h.update(json.dumps([document, approved_by, [(b.id, b.text) for b in blocks]]).encode())
    return h.hexdigest()


class SanitizedText(BaseModel):
    """Only the pipeline gate (release()) constructs this. LLM-facing code must accept this type, not str, and check
    is_sealed(): a hand-built or edited instance has no valid seal. This guards against mistakes, not against code that
    deliberately imports the key."""

    model_config = ConfigDict(frozen=True)

    document: str
    blocks: tuple[SanitizedBlock, ...]
    approved_by: str | None = None  # set when a human releases a REVIEW result
    seal: str = Field(default="", repr=False)

    def is_sealed(self) -> bool:
        return bool(self.seal) and hmac.compare_digest(self.seal, compute_seal(self.document, self.blocks, self.approved_by))

    def to_text(self) -> str:
        out: list[str] = []
        last = None
        for b in self.blocks:
            head = f"{b.locator.unit} {b.locator.index}" if b.locator.index is not None else b.locator.unit
            if head != last:
                out.append(f"\n## {head}")
                last = head
            prefix = f"[{b.locator.part}] " if b.locator.part else ""
            out.append(prefix + b.text)
        return "\n".join(out).strip() + "\n"


class PipelineResult(BaseModel):
    status: Status
    reasons: list[str] = Field(default_factory=list)
    document: ExtractedDocument | None = None
    findings: list[Finding] = Field(default_factory=list)
    sanitized_blocks: list[SanitizedBlock] = Field(default_factory=list)
    verification: Verification | None = None
    timings: dict[str, float] = Field(default_factory=dict)
    config_digest: str = ""
    notes: dict[str, Any] = Field(default_factory=dict)

    @property
    def safe_for_llm(self) -> bool:
        return self.status == Status.PASS

    def counts_by_type(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for f in self.findings:
            out[f.type] = out.get(f.type, 0) + 1
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))
