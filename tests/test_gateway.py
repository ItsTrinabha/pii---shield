from __future__ import annotations

import pytest

from pii_shield.errors import BlockedError
from pii_shield.gateway import ask_llm, echo_llm
from pii_shield.models import Locator, SanitizedBlock, SanitizedText
from pii_shield.pipeline import release

from .conftest import run_blocks


def _released() -> SanitizedText:
    return release(run_blocks(["Escalate to o.brennagh@example.test today."]))


def test_sealed_text_reaches_model_without_pii() -> None:
    seen = ask_llm(_released(), "Summarise the document.", echo_llm)
    assert "[EMAIL_1]" in seen and "example.test" not in seen


def test_hand_built_text_is_refused() -> None:
    blk = SanitizedBlock(id="b", locator=Locator(file="x", unit="page", index=1), text="raw o.brennagh@example.test")
    fake = SanitizedText(document="x", blocks=(blk,))
    with pytest.raises(BlockedError):
        ask_llm(fake, "Summarise.", echo_llm)


def test_tampered_text_is_refused() -> None:
    good = _released()
    blk = good.blocks[0].model_copy(update={"text": "raw o.brennagh@example.test"})
    tampered = good.model_copy(update={"blocks": (blk,)})
    with pytest.raises(BlockedError):
        ask_llm(tampered, "Summarise.", echo_llm)


def test_plain_string_is_refused() -> None:
    with pytest.raises(BlockedError):
        ask_llm("raw text", "Summarise.", echo_llm)  # type: ignore[arg-type]


def test_pii_in_instruction_is_refused() -> None:
    with pytest.raises(BlockedError):
        ask_llm(_released(), "Also email the result to o.brennagh@example.test", echo_llm)
