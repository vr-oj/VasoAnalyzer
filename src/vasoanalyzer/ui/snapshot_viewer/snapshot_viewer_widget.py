# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Canonical snapshot viewer widget skeleton."""

from __future__ import annotations

import logging
import os
import time

import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets

from vasoanalyzer.ui.snapshot_viewer.render_backends import (
    FrameData,
    PyqtgraphSnapshotRenderer,
    QtSnapshotRenderer,
    SnapshotRenderer,
)
from vasoanalyzer.ui.snapshot_viewer.snapshot_perf import log_perf, perf_enabled

log = logging.getLogger(__name__)


class SnapshotViewerWidget(QtWidgets.QWidget):
    """Minimal UI for displaying a snapshot frame."""

    frame_clicked = QtCore.pyqtSignal(QtCore.QPoint)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._rotation_deg = 0
        self.setMinimumHeight(220)

        self._label = QtWidgets.QLabel(self)
        self._label.setAlignment(QtCore.Qt.AlignCenter)
        self._label.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding
        )
        self._backend_name = self._resolve_backend()
        self._renderer: SnapshotRenderer
        if self._backend_name == "pyqtgraph":
            self._renderer = PyqtgraphSnapshotRenderer(
                self, show_native_controls=False
            )
        else:
            self._renderer = QtSnapshotRenderer(self)

        self._stack = QtWidgets.QStackedLayout(self)
        self._stack.setContentsMargins(6, 6, 6, 6)
        self._stack.addWidget(self._label)
        self._stack.addWidget(self._renderer.widget)

        self._show_placeholder()

    def set_frame(self, frame: FrameData | None, frame_index: int | None = None) -> None:
        """Render a new frame (numpy array, QImage, or QPixmap)."""
        if frame is None:
            self._show_placeholder()
            return

        perf_on = perf_enabled()
        start = time.perf_counter() if perf_on else None

        self._stack.setCurrentWidget(self._renderer.widget)
        try:
            self._renderer.set_frame(frame, frame_index=frame_index)
        except Exception:
            self._show_placeholder()
            return
        if start is not None:
            render_ms = (time.perf_counter() - start) * 1000.0
            frame_shape = None
            frame_dtype = None
            if isinstance(frame, np.ndarray):
                frame_shape = tuple(frame.shape)
                frame_dtype = str(frame.dtype)
            scale_ms = self._renderer.last_scale_ms
            log_perf(
                "render",
                backend=self._backend_name,
                path=self._backend_name,
                render_ms=round(render_ms, 3),
                scale_ms=round(scale_ms, 3) if scale_ms is not None else None,
                frame_shape=frame_shape,
                frame_dtype=frame_dtype,
                frame_index=frame_index,
            )

    def clear(self) -> None:
        self._show_placeholder()

    def set_rotation(self, angle_deg: int) -> None:
        self._rotation_deg = int(angle_deg) % 360
        with QtCore.QSignalBlocker(self._renderer.widget):
            self._renderer.set_rotation(self._rotation_deg)

    def rotate_cw_90(self) -> None:
        self.set_rotation(self._rotation_deg + 90)

    def rotate_ccw_90(self) -> None:
        self.set_rotation(self._rotation_deg - 90)

    def reset_rotation(self) -> None:
        self.set_rotation(0)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802
        if event.button() == QtCore.Qt.LeftButton:
            self.frame_clicked.emit(event.pos())
        super().mousePressEvent(event)

    def _show_placeholder(self) -> None:
        with QtCore.QSignalBlocker(self._renderer.widget):
            self._renderer.clear()
        self._stack.setCurrentWidget(self._label)
        self._label.clear()
        self._label.setText("No snapshot available")

    @staticmethod
    def _resolve_backend() -> str:
        value = os.environ.get("VA_SNAPSHOT_RENDER_BACKEND", "qt").strip().lower()
        if value in {"pyqtgraph", "pg"}:
            return "pyqtgraph"
        if value in {"qt", "native"}:
            return "qt"
        if value:
            log.warning("Unknown snapshot render backend '%s'; using qt", value)
        return "qt"
