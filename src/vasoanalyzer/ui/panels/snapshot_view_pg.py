# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""PyQtGraph-based snapshot/video viewer using ImageView with canonical time sync."""

from __future__ import annotations

import contextlib
import logging
import typing as _t

import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets
import pyqtgraph as pg

from vasoanalyzer.ui.theme import CURRENT_THEME

log = logging.getLogger(__name__)


class SnapshotViewPG(QtWidgets.QWidget):
    """
    Thin wrapper around :class:`pyqtgraph.ImageView` that exposes a simple API:

    - ``set_stack(stack, frame_trace_time)`` sets the video stack and aligns the
      ImageView time axis to the canonical trace time using ``xvals``.
    - ``currentTimeChanged`` emits experiment time (seconds) directly from
      PyQtGraph's ``sigTimeChanged``.
    - ``set_current_time`` / ``set_frame_index`` jump the ImageView to a time or
      frame index.
    """

    currentTimeChanged = QtCore.pyqtSignal(float)
    frameChanged = QtCore.pyqtSignal(int)

    def __init__(self, parent: _t.Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding
        )
        self.setMinimumHeight(220)

        self._stack: np.ndarray | None = None
        self._frame_trace_time: np.ndarray | None = None
        self._rotation_deg: int = 0
        self._suppress_signals: bool = False

        self.image_view = pg.ImageView(view=pg.PlotItem())
        try:
            view_box = self.image_view.getView()
            view_box.setMenuEnabled(False)
            view_box.setMouseEnabled(x=False, y=False)
            view_box.setAspectLocked(True)
            view_box.setDefaultPadding(0.0)
            bg_color = QtGui.QColor(CURRENT_THEME.get("snapshot_bg", "#2B2B2B"))
            view_box.setBackgroundColor(bg_color)
        except Exception:
            log.debug("SnapshotViewPG: unable to configure ImageView viewBox", exc_info=True)

        # Hide ROI/menu controls to keep the UI compact
        for btn_name in ("roiBtn", "menuBtn"):
            btn = getattr(self.image_view.ui, btn_name, None)
            if btn is not None:
                btn.hide()

        self.image_view.sigTimeChanged.connect(self._on_pg_time_changed)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.image_view)

        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu_requested)

    # ------------------ public API ------------------
    def set_stack(
        self,
        stack: np.ndarray,
        frame_trace_time: _t.Optional[np.ndarray] = None,
    ) -> None:
        """Set the image stack and canonical frame times (seconds)."""
        if stack is None:
            self._clear()
            return

        arr = np.asarray(stack)
        if arr.size == 0:
            self._clear()
            return

        arr = self._normalize_stack_to_grayscale(arr)
        n_frames = arr.shape[0]
        xvals = None
        if frame_trace_time is not None:
            xvals = np.asarray(frame_trace_time, dtype=float)
            if xvals.shape[0] != n_frames:
                log.warning(
                    "SnapshotViewPG: frame_trace_time length %d != n_frames %d; ignoring xvals",
                    xvals.shape[0],
                    n_frames,
                )
                xvals = None
            else:
                self._frame_trace_time = xvals
        else:
            self._frame_trace_time = None
        if xvals is None:
            self._frame_trace_time = None

        self._stack = arr
        axes = {"t": 0, "y": 1, "x": 2}
        if arr.ndim == 4:
            axes["c"] = 3

        self._suppress_signals = True
        try:
            self.image_view.setImage(
                arr,
                axes=axes,
                xvals=self._frame_trace_time,
                autoRange=True,
                autoLevels=True,
            )
            self.image_view.setCurrentIndex(0)
            self._apply_rotation()
        finally:
            self._suppress_signals = False

    def set_image_stack(
        self,
        stack: np.ndarray,
        frame_times: _t.Optional[np.ndarray] = None,
    ) -> None:
        """Compatibility alias for callers using the old API."""
        self.set_stack(stack, frame_times)

    def set_frame_index(self, index: int) -> None:
        """Programmatically jump to a given frame index."""
        if self._stack is None:
            return
        idx = int(np.clip(index, 0, self._stack.shape[0] - 1))
        self._suppress_signals = True
        try:
            self.image_view.setCurrentIndex(idx)
        finally:
            self._suppress_signals = False

    def current_frame_index(self) -> int | None:
        """Return the current frame index (best-effort)."""
        if self._stack is None:
            return None
        try:
            return int(getattr(self.image_view, "currentIndex", 0))
        except Exception:
            return None

    def set_current_time(self, t_s: float) -> None:
        """Jump to the frame nearest the given experiment time (seconds)."""
        if self._stack is None:
            return
        if self._frame_trace_time is None or self._frame_trace_time.size == 0:
            return
        idx = int(np.argmin(np.abs(self._frame_trace_time - float(t_s))))
        self.set_frame_index(idx)

    # rotation API
    def set_rotation(self, angle_deg: int) -> None:
        """Set absolute rotation in degrees (0, 90, 180, 270)."""
        self._rotation_deg = angle_deg % 360
        self._apply_rotation()

    def rotate_relative(self, delta_deg: int) -> None:
        self.set_rotation(self._rotation_deg + delta_deg)

    # ---------- internal ----------
    def _clear(self) -> None:
        self._stack = None
        self._frame_trace_time = None
        self._rotation_deg = 0
        with contextlib.suppress(Exception):
            self.image_view.clear()

    def _normalize_stack_to_grayscale(self, arr: np.ndarray) -> np.ndarray:
        """Return shape (n_frames, h, w[, c]) with grayscale frames where needed."""
        if arr.ndim == 2:
            arr = arr[np.newaxis, ...]  # (1, h, w)
        elif arr.ndim == 3 and arr.shape[-1] in (3, 4):
            arr = self._rgb_to_gray(arr)[np.newaxis, ...]
        elif arr.ndim == 4 and arr.shape[-1] in (3, 4):
            arr = self._rgb_to_gray(arr)
        elif arr.ndim < 3:
            raise ValueError(f"Unsupported stack ndim={arr.ndim}")
        return arr.astype(np.float32, copy=False)

    def _rgb_to_gray(self, arr: np.ndarray) -> np.ndarray:
        """Convert RGB/RGBA frames to grayscale using luminance weights."""
        if arr.shape[-1] == 3:
            r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
        elif arr.shape[-1] == 4:
            r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
        else:
            raise ValueError(f"Expected 3 or 4 channels, got {arr.shape[-1]}")
        gray = 0.299 * r + 0.587 * g + 0.114 * b
        return gray

    def _apply_rotation(self) -> None:
        """Apply rotation via ImageItem transform around its center."""
        try:
            image_item = self.image_view.getImageItem()
            if image_item is None or self._stack is None:
                return
            h, w = self._stack.shape[1], self._stack.shape[2]
            image_item.setTransformOriginPoint(w / 2.0, h / 2.0)
            transform = QtGui.QTransform()
            transform.rotate(self._rotation_deg)
            image_item.setTransform(transform)
        except Exception:
            log.debug("SnapshotViewPG: rotation failed", exc_info=True)

    # --- slots ---
    def _on_pg_time_changed(self, index: int, time_s: float | None) -> None:
        if self._suppress_signals:
            return
        idx_val = int(index)
        self.frameChanged.emit(idx_val)
        t_val = time_s
        if t_val is None and self._frame_trace_time is not None:
            if 0 <= idx_val < len(self._frame_trace_time):
                t_val = float(self._frame_trace_time[idx_val])
        if t_val is not None:
            self.currentTimeChanged.emit(float(t_val))

    def _on_context_menu_requested(self, pos: QtCore.QPoint) -> None:
        if self._stack is None:
            return
        menu = QtWidgets.QMenu(self)
        act_left = menu.addAction("Rotate 90° left")
        act_right = menu.addAction("Rotate 90° right")
        act_reset = menu.addAction("Reset rotation")
        action = menu.exec_(self.mapToGlobal(pos))
        if action is None:
            return
        if action == act_left:
            self.rotate_relative(-90)
        elif action == act_right:
            self.rotate_relative(90)
        elif action == act_reset:
            self.set_rotation(0)


__all__ = ["SnapshotViewPG"]
