"""Shared helpers. All values in tests are synthetic (555 numbers, 9xx SSNs, invented names)."""

from __future__ import annotations

import time

import pytest

from pii_shield.models import Block, DocStats, ExtractedDocument, Locator, PipelineResult, Status
from pii_shield.pipeline import Pipeline
from pii_shield.settings import Settings

FAST = Settings(use_ner=False)  # deterministic layers only: no spaCy model needed, runs in milliseconds


def make_doc(texts: list[str], source: str = "native", name: str = "synthetic.pdf") -> ExtractedDocument:
    blocks = []
    for i, t in enumerate(texts):
        loc = Locator(file=name, unit="page", index=1, block_id=f"b{i}")
        blocks.append(Block(id=f"b{i}", text=t, locator=loc, source=source, order=i))
    return ExtractedDocument(file_name=name, file_type="pdf", sha256="0" * 64, size_bytes=1, blocks=blocks,
                             stats=DocStats(page_count=1, block_count=len(blocks)))


def run_blocks(texts: list[str], settings: Settings = FAST, source: str = "native") -> PipelineResult:
    """Run detect -> mask -> verify -> gate on hand-made blocks (skips file parsing)."""
    doc = make_doc(texts, source=source)
    res = PipelineResult(status=Status.BLOCKED, config_digest=settings.digest())
    res.document = doc
    return Pipeline(settings)._process(doc, res, {}, time.time())


def sanitized(res: PipelineResult) -> str:
    return "\n".join(b.text for b in res.sanitized_blocks)


@pytest.fixture
def fast_settings() -> Settings:
    return FAST
