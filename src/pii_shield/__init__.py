"""Cloak: fail-closed PII detection and sanitisation gateway for LLM pipelines."""

__version__ = "1.0.0"

from .models import (  # noqa: E402
    Block,
    ExtractedDocument,
    Finding,
    Locator,
    PipelineResult,
    SanitizedText,
    Status,
)
from .pipeline import Pipeline, process_bytes, process_path  # noqa: E402

__all__ = [
    "Block",
    "ExtractedDocument",
    "Finding",
    "Locator",
    "Pipeline",
    "PipelineResult",
    "SanitizedText",
    "Status",
    "process_bytes",
    "process_path",
]
