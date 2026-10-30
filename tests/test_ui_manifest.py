"""Feature 9: the web app manifest is valid and every icon exists at its declared size.

Runs ui/scripts/check-manifest.mjs (no dependencies, no network) so the
pytest gate covers it. Skips only when node is not installed.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

UI = Path(__file__).resolve().parents[1] / "ui"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_manifest_check_passes_on_ui_public() -> None:
    result = subprocess.run(
        ["node", "scripts/check-manifest.mjs", "public"],
        cwd=UI, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "manifest check OK" in result.stdout


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_manifest_check_fails_on_a_wrong_icon_size(tmp_path: Path) -> None:
    for name in ("favicon.svg", "apple-touch-icon.svg", "apple-touch-icon.png", "favicon-32.png"):
        shutil.copy(UI / "public" / name, tmp_path / name)
    text = (UI / "public" / "manifest.webmanifest").read_text(encoding="utf-8")
    (tmp_path / "manifest.webmanifest").write_text(text.replace('"180x180"', '"192x192"'), encoding="utf-8")
    result = subprocess.run(
        ["node", str(UI / "scripts" / "check-manifest.mjs"), str(tmp_path)],
        cwd=UI, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 1
    assert "declares 192x192, file is 180x180" in result.stderr
