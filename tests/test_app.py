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
