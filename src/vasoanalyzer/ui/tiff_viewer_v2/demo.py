# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Standalone demo harness for the TIFF viewer v2."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import numpy as np
from PyQt5 import QtWidgets

from vasoanalyzer.io.tiffs import load_tiff
from vasoanalyzer.ui.tiff_viewer_v2.page_time_map import (
    PageTimeMap,
    derive_page_time_map_from_trace,
)
from vasoanalyzer.ui.tiff_viewer_v2.widget import TiffStackViewerWidget


def _load_trace_csv(path: Path):
    try:
        import pandas as pd  # type: ignore
    except Exception:
        return None
    try:
        return pd.read_csv(path)
    except Exception:
        return None


def _generate_synthetic_frames(count: int = 120, height: int = 240, width: int = 320):
    frames = []
    base = np.linspace(0, 255, width, dtype=np.uint8)
    gradient = np.tile(base, (height, 1))
    for i in range(count):
        frame = gradient.copy()
        band_center = int((i / max(1, count - 1)) * (width - 1))
        start = max(0, band_center - 6)
        end = min(width, band_center + 6)
        frame[:, start:end] = 255
        shift = (i * 3) % height
        frame = np.roll(frame, shift, axis=0)
        frames.append(frame)
    return frames


def _resolve_path(value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser()
    if path.exists():
        return path
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="TIFF Viewer v2 demo")
    parser.add_argument("--tiff", type=str, default=None, help="Path to TIFF stack")
    parser.add_argument("--trace", type=str, default=None, help="Path to trace CSV")
    args = parser.parse_args()

    tiff_path = _resolve_path(args.tiff) or _resolve_path(
        os.environ.get("VA_TIFF_VIEWER_V2_DEMO_TIFF")
    )
    trace_path = _resolve_path(args.trace) or _resolve_path(
        os.environ.get("VA_TIFF_VIEWER_V2_DEMO_TRACE")
    )

    frames = None
    page_time_map = None

    if tiff_path is not None:
        frames, _metadata, _info = load_tiff(str(tiff_path), max_frames=None)
        if trace_path is not None:
            trace_df = _load_trace_csv(trace_path)
            if trace_df is not None:
                page_time_map = derive_page_time_map_from_trace(
                    trace_df, expected_page_count=len(frames)
                )
        if page_time_map is None:
            page_time_map = PageTimeMap.invalid("Sync unavailable: trace not provided")

    if frames is None:
        frames = _generate_synthetic_frames()
        page_time_map = PageTimeMap.from_times([idx / 30.0 for idx in range(len(frames))])

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = QtWidgets.QMainWindow()
    window.setWindowTitle("TIFF Viewer v2 Demo")
    viewer = TiffStackViewerWidget()
    viewer.set_source(frames, page_time_map=page_time_map)
    viewer.set_playing(True)
    window.setCentralWidget(viewer)
    window.resize(900, 700)
    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
