# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Experimental PyQtGraph snapshot renderer (ImageView-based)."""

from __future__ import annotations

import numpy as np
from PyQt5 import QtWidgets

from vasoanalyzer.ui.snapshot_viewer.experimental.snapshot_view_pg import SnapshotViewPG
from vasoanalyzer.ui.snapshot_viewer.qimage_cache import QImageLruCache
from vasoanalyzer.ui.snapshot_viewer.render_backends import FrameData


class PyqtgraphSnapshotRenderer:
    """PyQtGraph snapshot renderer (ImageView)."""

    def __init__(
        self,
        parent: QtWidgets.QWidget | None = None,
        *,
        show_native_controls: bool = False,
    ) -> None:
        self._view = SnapshotViewPG(parent, show_native_controls=show_native_controls)
        self._rotation_deg = 0

    @property
    def widget(self) -> QtWidgets.QWidget:
        return self._view

    @property
    def last_scale_ms(self) -> float | None:
        return None

    @property
    def last_convert_ms(self) -> float | None:
        return None

    @property
    def last_cache_hit(self) -> bool | None:
        return None

    @property
    def cache_bytes(self) -> int | None:
        return None

    @property
    def cache_max_bytes(self) -> int | None:
        return None

    @property
    def cache(self) -> QImageLruCache | None:
        return None

    def set_frame(self, frame: FrameData, frame_index: int | None = None) -> None:
        if not isinstance(frame, np.ndarray):
            raise ValueError("PyQtGraph renderer expects numpy frames")
        self._view.set_stack(frame)
        if self._rotation_deg:
            self._view.set_rotation(self._rotation_deg)

    def clear(self) -> None:
        self._view.set_stack(None)

    def set_playing(self, playing: bool) -> None:
        return

    def set_rotation(self, angle_deg: int) -> None:
        self._rotation_deg = int(angle_deg) % 360
        self._view.set_rotation(self._rotation_deg)


__all__ = ["PyqtgraphSnapshotRenderer"]
