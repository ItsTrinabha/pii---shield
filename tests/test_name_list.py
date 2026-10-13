"""A name-shaped line between two names is a name ('KC Burney' in a user list); a role ('VP InfoSec') is not."""

from __future__ import annotations

from pii_shield.settings import Settings

from .conftest import run_blocks

NER = Settings(use_gliner=False)  # the name rules use spaCy NER as one signal


def _masked(r) -> set[str]:
    blocks = {b.id: b for b in r.document.blocks}
    return {blocks[f.block_id].text[f.start:f.end] for f in r.findings if f.type == "PERSON"}


def test_initials_in_name_list_are_masked() -> None:
    r = run_blocks(["Ottilie Brennagh", "KC Burney", "Marcus Whitfield"], NER)
    assert "KC Burney" in _masked(r)


def test_role_abbreviation_between_names_is_not_a_name() -> None:
    r = run_blocks(["Ottilie Brennagh", "VP InfoSec", "Marcus Whitfield"], NER)
    assert "VP InfoSec" not in _masked(r)
