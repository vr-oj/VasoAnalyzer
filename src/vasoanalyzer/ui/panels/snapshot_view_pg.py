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

from vasoanalyzer.ui.theme import CURRENT_THEME, hex_to_pyqtgraph_color

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

    def __init__(
        self,
        parent: _t.Optional[QtWidgets.QWidget] = None,
        show_native_controls: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding
        )
        self.setMinimumHeight(220)

        self._stack: np.ndarray | None = None
        self._frame_trace_time: np.ndarray | None = None
        self._rotation_deg: int = 0
        self._suppress_signals: bool = False
        self._default_fps: float = 10.0
        self._native_controls: dict[str, _t.Any] | None = None

        self.image_view = pg.ImageView(view=pg.PlotItem())
        try:
            plot_item = self.image_view.getView()
            # Hide axes for cleaner video display
            plot_item.hideAxis("left")
            plot_item.hideAxis("bottom")
            # Configure ViewBox
            view_box = plot_item.getViewBox()
            view_box.setMenuEnabled(False)
            view_box.setMouseEnabled(x=False, y=False)
            view_box.setAspectLocked(True)
            view_box.setDefaultPadding(0.0)
            bg_hex = CURRENT_THEME.get("snapshot_bg", "#2B2B2B")
            bg_rgb = hex_to_pyqtgraph_color(bg_hex)
            view_box.setBackgroundColor(bg_rgb)
        except Exception:
            log.debug(
                "SnapshotViewPG: unable to configure ImageView viewBox", exc_info=True
            )

        # Hide non-essential UI elements for clean video display
        # Canonical pattern: custom buttons in parent UI, native engine underneath
        for btn_name in ("roiBtn", "menuBtn"):
            btn = getattr(self.image_view.ui, btn_name, None)
            if btn is not None:
                btn.hide()

        # Hide histogram - we use custom controls instead
        with contextlib.suppress(Exception):
            histogram = getattr(self.image_view.ui, "histogram", None)
            if histogram is not None:
                histogram.hide()
                histogram.setMaximumHeight(0)

        # Hide the built-in ROI/timeline plot to reclaim vertical space; we drive playback externally.
        self._collapse_native_timeline()

        # Note: PyQtGraph's native playback controls (playBtn, timeSlider, roiPlot)
        # are not visible by default in modern PyQtGraph. We use custom QPushButtons
        # in the main window that call image_view.play(rate) and image_view.stop()
        # directly - this is the official PyQtGraph pattern for custom UI integration.

        self.image_view.sigTimeChanged.connect(self._on_pg_time_changed)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.image_view)
        if show_native_controls:
            self._init_native_controls(layout)

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

        # Reset orientation for each new stack before applying transforms.
        self.set_rotation(0)

        arr = self._normalize_stack(arr)
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

        self._update_native_controls_for_stack(n_frames)

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
        self._collapse_native_timeline()

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
        self._sync_slider_to_index(idx)

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

    def rotate_cw_90(self) -> None:
        """Rotate 90 degrees clockwise."""
        self.rotate_relative(90)

    def rotate_ccw_90(self) -> None:
        """Rotate 90 degrees counter-clockwise."""
        self.rotate_relative(-90)

    def reset_rotation(self) -> None:
        """Reset orientation to 0 degrees."""
        self.set_rotation(0)

    # playback API (canonical PyQtGraph pattern)
    def play(self, fps: float = 10.0) -> None:
        """Start playback at specified frame rate using native PyQtGraph engine.

        Args:
            fps: Frames per second (playback rate)
        """
        if self._stack is None:
            self._update_native_controls_playing(False)
            return
        rate = float(fps if fps is not None else self._default_fps)
        with contextlib.suppress(Exception):
            self.image_view.play(rate=rate)
        self._update_native_controls_playing(self.is_playing(), rate)

    def stop(self) -> None:
        """Stop playback using native PyQtGraph engine."""
        with contextlib.suppress(Exception):
            # ImageView.stop() was removed in modern PyQtGraph; play(0) pauses.
            self.image_view.play(0)
        self._update_native_controls_playing(False)

    def is_playing(self) -> bool:
        """Check if playback is currently active."""
        try:
            # PyQtGraph ImageView stores playback state in timer
            timer = getattr(self.image_view, "playTimer", None)
            return timer is not None and timer.isActive()
        except Exception:
            return False

    # ---------- internal ----------
    def _clear(self) -> None:
        self._stack = None
        self._frame_trace_time = None
        self._rotation_deg = 0
        with contextlib.suppress(Exception):
            self.image_view.clear()
        self._update_native_controls_for_stack(0)
        self._update_native_controls_playing(False)

    def _normalize_stack(self, arr: np.ndarray) -> np.ndarray:
        """Return shape (n_frames, h, w[, c]) preserving RGB/RGBA color channels."""
        is_rgb = False

        if arr.ndim == 2:
            # Single grayscale frame
            arr = arr[np.newaxis, ...]  # (1, h, w)
        elif arr.ndim == 3:
            # Could be either (h, w, c) single RGB frame or (n, h, w) grayscale stack
            if arr.shape[-1] in (3, 4):
                # Single RGB/RGBA frame: (h, w, c) → (1, h, w, c)
                arr = arr[np.newaxis, ...]
                is_rgb = True
            else:
                # Grayscale stack: (n, h, w) - already correct
                pass
        elif arr.ndim == 4:
            # RGB/RGBA stack: (n, h, w, c) - already correct
            if arr.shape[-1] not in (3, 4):
                raise ValueError(
                    f"4D array must have 3 or 4 channels, got {arr.shape[-1]}"
                )
            is_rgb = True
        elif arr.ndim < 2:
            raise ValueError(f"Unsupported stack ndim={arr.ndim}")

        # For RGB data, keep as uint8 if possible for PyQtGraph, otherwise ensure proper scaling
        if is_rgb:
            # If uint8, keep as-is (0-255 range)
            if arr.dtype == np.uint8:
                return arr
            # If float and values > 1, assume 0-255 range and convert to uint8
            elif np.issubdtype(arr.dtype, np.floating):
                if arr.max() > 1.0:
                    return np.clip(arr, 0, 255).astype(np.uint8)
                else:
                    # Already 0-1 range, scale to 0-255 for uint8
                    return (arr * 255).astype(np.uint8)
            else:
                # Other integer types, clip to 0-255 and convert to uint8
                return np.clip(arr, 0, 255).astype(np.uint8)
        else:
            # Grayscale: convert to float32 for PyQtGraph's auto-leveling
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

    def _collapse_native_timeline(self) -> None:
        """Hide/collapse the built-in ImageView timeline/ROI plot."""
        with contextlib.suppress(Exception):
            roi_plot = getattr(self.image_view.ui, "roiPlot", None)
            if roi_plot is not None:
                roi_plot.hide()
                roi_plot.setVisible(False)
                roi_plot.setMinimumHeight(0)
                roi_plot.setMaximumHeight(0)
            timeline = getattr(self.image_view, "timeLine", None)
            if timeline is not None:
                timeline.hide()
            splitter = getattr(self.image_view.ui, "splitter", None)
            if splitter is not None:
                splitter.setSizes([1, 0])
                splitter.setHandleWidth(0)
    # --- native controls helpers ---
    def _init_native_controls(self, layout: QtWidgets.QVBoxLayout) -> None:
        """Optionally render PyQtGraph-native playback controls."""
        controls = QtWidgets.QWidget(self)
        row = QtWidgets.QHBoxLayout(controls)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(8)

        play_btn = QtWidgets.QToolButton(controls)
        play_btn.setCheckable(True)
        play_btn.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        play_btn.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_MediaPlay))
        play_btn.setText("Play")
        play_btn.setEnabled(False)
        play_btn.toggled.connect(self._on_native_play_toggled)
        row.addWidget(play_btn, 0, QtCore.Qt.AlignVCenter)

        slider = QtWidgets.QSlider(QtCore.Qt.Horizontal, controls)
        slider.setMinimum(0)
        slider.setMaximum(0)
        slider.setSingleStep(1)
        slider.setEnabled(False)
        slider.valueChanged.connect(self._on_native_slider_changed)

        fps_spin = pg.SpinBox(
            value=self._default_fps,
            step=1.0,
            bounds=(1.0, 200.0),
            decimals=0,
            int=True,
            siPrefix=False,
            suffix=" fps",
        )

        # Match all controls to button height for perfect alignment
        btn_width = play_btn.sizeHint().width()
        btn_height = play_btn.sizeHint().height()

        # Ensure spinbox is wide enough for "200 fps" and matches button
        target_width = max(btn_width, 90)  # 90px accommodates 3-digit fps
        fps_spin.setMinimumWidth(target_width)

        if btn_height > 0:
            fps_spin.setFixedHeight(btn_height)
            slider.setFixedHeight(btn_height)

        fps_spin.setEnabled(False)
        fps_spin.valueChanged.connect(self._on_native_fps_changed)

        # Add widgets with vertical center alignment
        row.addWidget(slider, 1, QtCore.Qt.AlignVCenter)
        row.addWidget(fps_spin, 0, QtCore.Qt.AlignVCenter)

        self._native_controls = {
            "widget": controls,
            "play_btn": play_btn,
            "slider": slider,
            "fps_spin": fps_spin,
        }
        layout.addWidget(controls)

    def _update_native_controls_for_stack(self, n_frames: int) -> None:
        if not self._native_controls:
            return
        slider: QtWidgets.QSlider = self._native_controls["slider"]
        play_btn: QtWidgets.QToolButton = self._native_controls["play_btn"]
        fps_spin: pg.SpinBox = self._native_controls["fps_spin"]
        enabled = n_frames > 0
        play_btn.setEnabled(enabled)
        slider.setEnabled(enabled)
        fps_spin.setEnabled(enabled)
        slider.setMaximum(max(0, n_frames - 1))
        with QtCore.QSignalBlocker(slider):
            slider.setValue(0)

    def _update_native_controls_playing(
        self, playing: bool, fps: float | None = None
    ) -> None:
        if not self._native_controls:
            return
        play_btn: QtWidgets.QToolButton = self._native_controls["play_btn"]
        icon = (
            QtWidgets.QStyle.SP_MediaPause if playing else QtWidgets.QStyle.SP_MediaPlay
        )
        text = "Pause" if playing else "Play"
        with QtCore.QSignalBlocker(play_btn):
            play_btn.setChecked(playing)
            play_btn.setIcon(self.style().standardIcon(icon))
            play_btn.setText(text)
        if fps is not None:
            fps_spin: pg.SpinBox = self._native_controls["fps_spin"]
            with QtCore.QSignalBlocker(fps_spin):
                fps_spin.setValue(float(fps))

    def _sync_slider_to_index(self, idx: int) -> None:
        if not self._native_controls:
            return
        slider: QtWidgets.QSlider = self._native_controls["slider"]
        with QtCore.QSignalBlocker(slider):
            slider.setValue(idx)

    def _on_native_play_toggled(self, checked: bool) -> None:
        if self._stack is None:
            self._update_native_controls_playing(False)
            return
        fps_spin: pg.SpinBox = self._native_controls["fps_spin"]
        target_fps = float(fps_spin.value())
        if checked:
            self.play(target_fps)
        else:
            self.stop()

    def _on_native_slider_changed(self, idx: int) -> None:
        if self._stack is None:
            return
        target_idx = int(np.clip(idx, 0, self._stack.shape[0] - 1))
        self.image_view.setCurrentIndex(target_idx)

    def _on_native_fps_changed(self, fps_value: object) -> None:
        if not self.is_playing():
            return
        with contextlib.suppress(Exception):
            fps = float(fps_value)
            self.play(fps=fps)

    # --- slots ---
    def _on_pg_time_changed(self, index: int, time_s: float | None) -> None:
        if self._suppress_signals:
            return
        idx_val = int(index)
        self.frameChanged.emit(idx_val)
        self._sync_slider_to_index(idx_val)
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
            self.rotate_ccw_90()
        elif action == act_right:
            self.rotate_cw_90()
        elif action == act_reset:
            self.reset_rotation()


__all__ = ["SnapshotViewPG"]
