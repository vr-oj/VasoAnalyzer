# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Snapshot viewer factory helpers."""

from __future__ import annotations

import os

from PyQt5 import QtWidgets


def snapshot_viewer_v2_enabled() -> bool:
    value = os.environ.get("VA_SNAPSHOT_VIEWER_V2", "").strip().lower()
    if not value:
        return True
    return value not in {"0", "false", "no", "off"}


def create_snapshot_viewer_widget(
    parent: QtWidgets.QWidget | None,
) -> QtWidgets.QWidget:
    if snapshot_viewer_v2_enabled():
        from vasoanalyzer.ui.tiff_viewer_v2 import TiffStackViewerWidget

        return TiffStackViewerWidget(parent)

    from vasoanalyzer.ui.snapshot_viewer.snapshot_viewer_widget import (
        SnapshotViewerWidget,
    )

    return SnapshotViewerWidget(parent)


__all__ = ["create_snapshot_viewer_widget", "snapshot_viewer_v2_enabled"]
