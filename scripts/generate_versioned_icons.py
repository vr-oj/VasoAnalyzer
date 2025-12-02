"""
Generate version-stamped app icons for PyInstaller builds.

Reads the current APP_VERSION from utils.config and overlays it on the base
VasoAnalyzer icon to produce platform-specific icon files:
- build/icons/VasoAnalyzerIcon.versioned.ico
- build/icons/VasoAnalyzerIcon.versioned.icns
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Tuple

from PIL import Image, ImageDraw, ImageFont

# Project-relative paths
PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASE_ICON = (
    PROJECT_ROOT / "src" / "vasoanalyzer" / "VasoAnalyzerIcon.icns"
    if (PROJECT_ROOT / "src" / "vasoanalyzer" / "VasoAnalyzerIcon.icns").exists()
    else PROJECT_ROOT / "src" / "vasoanalyzer" / "VasoAnalyzerIcon.ico"
)
OUTPUT_DIR = PROJECT_ROOT / "build" / "icons"


def _load_version() -> str:
    import importlib.util

    cfg_path = PROJECT_ROOT / "src" / "utils" / "config.py"
    spec = importlib.util.spec_from_file_location("config", cfg_path)
    if spec is None or spec.loader is None:
        return "0.0.0"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, "APP_VERSION", "0.0.0")


def _render_badge(base: Image.Image, version: str) -> Image.Image:
    img = base.convert("RGBA")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", size=max(12, img.width // 12))
    except Exception:
        font = ImageFont.load_default()
    padding = max(4, img.width // 32)
    text = f"v{version}"
    text_w, text_h = draw.textsize(text, font=font)
    box_w = text_w + padding * 2
    box_h = text_h + padding
    x1 = img.width - box_w - padding
    y1 = img.height - box_h - padding
    rect = (x1, y1, x1 + box_w, y1 + box_h)
    draw.rounded_rectangle(rect, radius=padding, fill=(0, 0, 0, 180))
    draw.text((x1 + padding, y1 + padding // 2), text, font=font, fill=(255, 255, 255, 230))
    return img


def generate_versioned_icons() -> Tuple[Path, Path]:
    version = _load_version()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    base = Image.open(BASE_ICON)
    # Use largest frame as base
    if hasattr(base, "n_frames") and base.n_frames > 1:
        base.seek(base.n_frames - 1)
    largest = base.copy()
    if largest.width != largest.height:
        size = max(largest.width, largest.height)
        largest = largest.resize((size, size), Image.LANCZOS)

    stamped = _render_badge(largest, version)

    sizes = [16, 24, 32, 48, 64, 128, 256]
    ico_path = OUTPUT_DIR / "VasoAnalyzerIcon.versioned.ico"
    stamped.save(ico_path, format="ICO", sizes=[(s, s) for s in sizes])

    icns_path = OUTPUT_DIR / "VasoAnalyzerIcon.versioned.icns"
    stamped.save(icns_path, format="ICNS")

    return ico_path, icns_path


if __name__ == "__main__":
    ico, icns = generate_versioned_icons()
    print(f"Generated icons:\n  {ico}\n  {icns}")
