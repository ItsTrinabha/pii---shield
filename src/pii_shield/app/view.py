"""Display rules for the demo UI, kept out of the Streamlit script so they can be unit-tested."""

from __future__ import annotations

from ..models import PipelineResult


def hidden_sanitized_blocks(r: PipelineResult, reveal: bool) -> set[str]:
    """Sanitised blocks that still carry a verifier HARD hit contain residual PII (that is why the document is BLOCKED),
    so with reveal off they are hidden like the original text."""
    if reveal or r.verification is None:
        return set()
    return {h.block_id for h in r.verification.hard_hits}
