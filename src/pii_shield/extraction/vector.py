"""Optional rendering of vector images (EMF/WMF) so text drawn as glyph paths can still be OCR'd.

Uses a local LibreOffice if present. Failure is not silent: the image is reported as unsupported media and the
document is held for human review (fail-closed)."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from ..settings import Settings


def have_renderer() -> bool:
    return shutil.which("soffice") is not None


def render_vector_to_png(data: bytes, ext: str, settings: Settings) -> bytes | None:
    exe = shutil.which("soffice")
    if not exe or ext.lower() not in (".emf", ".wmf"):
        return None
    env = os.environ.copy()
    env["SAL_USE_VCLPLUGIN"] = "svp"
    pre = os.environ.get("PII_SHIELD_SOFFICE_PRELOAD")
    if pre:
        env["LD_PRELOAD"] = pre
    with tempfile.TemporaryDirectory(prefix="pii_shield_vec_") as td, tempfile.TemporaryDirectory(prefix="pii_shield_lo_") as prof:
        src = Path(td) / f"img{ext.lower()}"
        src.write_bytes(data)
        try:
            subprocess.run(
                [exe, f"-env:UserInstallation={Path(prof).as_uri()}", "--headless", "--convert-to", "png", "--outdir", td, str(src)],
                env=env, capture_output=True, timeout=min(90, settings.limits.ocr_timeout_s), check=False,
            )
        except (subprocess.TimeoutExpired, OSError):
            return None
        out = Path(td) / "img.png"
        return out.read_bytes() if out.exists() else None
