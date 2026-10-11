"""Smoke test for the Streamlit UI: it renders, and a document that cannot be processed shows BLOCKED, not content."""

from __future__ import annotations

from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "src" / "pii_shield" / "app" / "main.py"


def test_app_renders_empty_state() -> None:
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(APP), default_timeout=60).run()
    assert not at.exception
    assert at.header[0].value.startswith("Upload")


def test_reveal_is_off_by_default() -> None:
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(APP), default_timeout=60).run()
    reveal = [t for t in at.sidebar.toggle if "Reveal" in t.label]
    assert reveal and reveal[0].value is False


@pytest.mark.slow
def test_app_runs_on_sample() -> None:
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(APP), default_timeout=900).run()
    at.sidebar.radio[0].set_value("Cadence sample").run()
    assert not at.exception
    assert at.error or at.warning or at.success  # a status banner is always shown


def test_blocks_with_residual_pii_are_hidden_unless_revealed() -> None:
    from pii_shield.app.view import hidden_sanitized_blocks
    from pii_shield.models import Locator, PipelineResult, Status, Verification, VerificationHit

    loc = Locator(file="x.pdf", unit="page", index=1, block_id="b1")
    hit = VerificationHit(severity="HARD", rule="residual-email", block_id="b1", locator=loc, start=0, end=5)
    soft = VerificationHit(severity="SOFT", rule="possible-unmasked-name", block_id="b2", locator=loc, start=0, end=5)
    r = PipelineResult(status=Status.BLOCKED, config_digest="x")
    r.verification = Verification(passed=False, hard_hits=[hit], soft_hits=[soft])
    assert hidden_sanitized_blocks(r, reveal=False) == {"b1"}
    assert hidden_sanitized_blocks(r, reveal=True) == set()
    r.verification = None
    assert hidden_sanitized_blocks(r, reveal=False) == set()
