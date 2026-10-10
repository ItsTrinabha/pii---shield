"""The only door to an LLM. Accepts a sealed SanitizedText (produced by release()), never a str.

The model call itself is injected (`llm: Callable[[str], str]`), so the gateway stays provider-neutral and offline by
default; any network client is the integrator's choice and only ever receives verified text."""

from __future__ import annotations

from collections.abc import Callable

from .errors import BlockedError
from .models import Locator, SanitizedBlock, SanitizedText
from .verification import verify


def ask_llm(text: SanitizedText, instruction: str, llm: Callable[[str], str], max_chars: int = 200_000) -> str:
    if not isinstance(text, SanitizedText) or not text.is_sealed():
        raise BlockedError("refused: input was not produced by the release gate (unsealed or modified)")
    # the instruction is caller-written and could itself carry PII: run it through the same independent verifier
    probe = SanitizedBlock(id="instruction", locator=Locator(file="instruction", unit="prompt"), text=instruction)
    v = verify([probe])
    if v.hard_hits:
        raise BlockedError(f"refused: instruction contains {len(v.hard_hits)} PII-like value(s)")
    body = text.to_text()
    if len(body) > max_chars:
        raise BlockedError("refused: sanitised document exceeds the configured prompt size")
    return llm(f"{instruction}\n\n<document name=\"{text.document}\">\n{body}</document>")


def echo_llm(prompt: str) -> str:
    """Offline stand-in for a model, used by the demo and tests: returns what the model would have received."""
    return prompt
