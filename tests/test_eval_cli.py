"""The eval runner caps OCR threads (a full run was killed for low memory with the default of up to 4)."""

from __future__ import annotations

from pii_shield.eval.__main__ import parse_args, settings_from_args


def test_eval_defaults_to_two_ocr_workers() -> None:
    assert settings_from_args(parse_args([])).ocr_workers == 2


def test_eval_ocr_workers_never_below_one() -> None:
    assert settings_from_args(parse_args(["--ocr-workers", "0"])).ocr_workers == 1


def test_render_ocr_flag() -> None:
    a = parse_args(["--render-ocr", "--render-dpi", "150"])
    assert a.render_ocr and a.render_dpi == 150
    assert not parse_args([]).render_ocr
