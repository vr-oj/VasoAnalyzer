# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Snapshot render backends (Qt-native)."""

from __future__ import annotations

import time
from typing import Protocol, Union

import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets

from vasoanalyzer.ui.snapshot_viewer.qimage_cache import (
    QImageLruCache,
    qimage_cache_key,
)
from vasoanalyzer.ui.snapshot_viewer.snapshot_perf import log_perf, perf_enabled
from vasoanalyzer.ui.theme import CURRENT_THEME

FrameData = Union[np.ndarray, QtGui.QImage, QtGui.QPixmap]


def numpy_rgb_to_qimage(arr: np.ndarray) -> QtGui.QImage:
    """Convert an RGB uint8 ndarray to a deep-copied QImage."""
    assert arr.dtype == np.uint8 and arr.ndim == 3 and arr.shape[2] == 3
    arr = np.ascontiguousarray(arr)
    height, width, _channels = arr.shape
    bytes_per_line = 3 * width
    qimage = QtGui.QImage(
        arr.data,
        width,
        height,
        bytes_per_line,
        QtGui.QImage.Format_RGB888,
    )
    return qimage.copy()


def _ensure_uint8(arr: np.ndarray) -> np.ndarray:
    if arr.dtype == np.uint8:
        return arr
    arr_f = arr.astype(float)
    vmax = float(arr_f.max()) if arr_f.size else 0.0
    if vmax <= 0:
        return np.zeros_like(arr_f, dtype=np.uint8)
    scaled = np.clip(arr_f / vmax * 255.0, 0.0, 255.0)
    return scaled.astype(np.uint8)


def _numpy_gray_to_qimage(arr: np.ndarray) -> QtGui.QImage:
    arr = np.ascontiguousarray(arr)
    height, width = arr.shape
    qimage = QtGui.QImage(
        arr.data,
        width,
        height,
        width,
        QtGui.QImage.Format_Grayscale8,
    )
    return qimage.copy()


def numpy_to_qimage(arr: np.ndarray) -> QtGui.QImage | None:
    """Convert a numpy array to a QImage when possible."""
    arr = np.asarray(arr)
    if arr.size == 0:
        return None

    if arr.ndim == 2:
        arr = _ensure_uint8(arr)
        return _numpy_gray_to_qimage(arr)
    if arr.ndim == 3:
        if arr.shape[2] == 1:
            arr = arr[:, :, 0]
            arr = _ensure_uint8(arr)
            return _numpy_gray_to_qimage(arr)
        if arr.shape[2] == 3:
            arr = _ensure_uint8(arr)
            return numpy_rgb_to_qimage(arr)
        return None
    return None


def coerce_qimage(frame: FrameData) -> QtGui.QImage | None:
    """Coerce supported frame types into a QImage."""
    if isinstance(frame, QtGui.QImage):
        return frame
    if isinstance(frame, QtGui.QPixmap):
        return frame.toImage()
    if isinstance(frame, np.ndarray):
        return numpy_to_qimage(frame)
    return None


class SnapshotRenderer(Protocol):
    """Minimal renderer interface for snapshot frames."""

    @property
    def widget(self) -> QtWidgets.QWidget: ...

    def set_frame(self, frame: FrameData, frame_index: int | None = None) -> None: ...

    def clear(self) -> None: ...

    def set_playing(self, playing: bool) -> None: ...

    def set_rotation(self, angle_deg: int) -> None: ...

    @property
    def last_convert_ms(self) -> float | None: ...

    @property
    def last_scale_ms(self) -> float | None: ...

    @property
    def last_cache_hit(self) -> bool | None: ...

    @property
    def cache_bytes(self) -> int | None: ...

    @property
    def cache_max_bytes(self) -> int | None: ...

    @property
    def cache(self) -> QImageLruCache | None: ...


class QtFrameView(QtWidgets.QWidget):
    """Lightweight widget that paints a cached, scaled QImage."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._frame_qimage: QtGui.QImage | None = None
        self._scaled_qimage: QtGui.QImage | None = None
        self._scaled_for_size = QtCore.QSize()
        self._scaled_for_dpr = 1.0
        self._scaled_transform_mode = QtCore.Qt.SmoothTransformation
        self._scaled_target_rect = QtCore.QRectF()
        self._rotation_deg = 0
        self._scale_dirty = False
        self._last_scale_ms: float | None = None
        self._current_frame_index: int | None = None
        self._playing = False
        self.setMinimumHeight(220)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding
        )

    @property
    def last_scale_ms(self) -> float | None:
        return self._last_scale_ms

    def set_frame(self, qimage: QtGui.QImage | None, frame_index: int | None = None) -> None:
        self._frame_qimage = qimage
        self._current_frame_index = frame_index
        self._scale_dirty = True
        self._update_scaled_pixmap()
        self.update()

    def clear(self) -> None:
        self._frame_qimage = None
        self._scaled_qimage = None
        self._scaled_for_size = QtCore.QSize()
        self._scaled_for_dpr = 1.0
        self._scaled_transform_mode = QtCore.Qt.SmoothTransformation
        self._scaled_target_rect = QtCore.QRectF()
        self._scale_dirty = False
        self._last_scale_ms = None
        self._current_frame_index = None
        self.update()

    def set_rotation(self, angle_deg: int) -> None:
        angle = int(angle_deg) % 360
        if angle == self._rotation_deg:
            return
        self._rotation_deg = angle
        self._scale_dirty = True
        self._update_scaled_pixmap()
        self.update()

    def set_playing(self, playing: bool) -> None:
        playing = bool(playing)
        if self._playing == playing:
            return
        self._playing = playing
        self._scale_dirty = True
        self._update_scaled_pixmap()
        self.update()

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._scale_dirty = True
        self._update_scaled_pixmap()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802
        start = time.perf_counter() if perf_enabled() else None
        painter = QtGui.QPainter(self)
        bg = CURRENT_THEME.get("snapshot_bg", "#000000")
        painter.fillRect(self.rect(), QtGui.QColor(bg))
        image = self._scaled_qimage
        if image is not None:
            painter.drawImage(self._scaled_target_rect, image)
        if start is not None:
            paint_ms = (time.perf_counter() - start) * 1000.0
            log_perf(
                "paint",
                backend="qt",
                paint_ms=round(paint_ms, 3),
                frame_index=self._current_frame_index,
            )

    def _update_scaled_pixmap(self) -> None:
        if self._frame_qimage is None:
            self._scaled_qimage = None
            self._scaled_for_size = QtCore.QSize()
            self._scaled_target_rect = QtCore.QRectF()
            self._last_scale_ms = None
            return

        size = self.size()
        if size.width() <= 0 or size.height() <= 0:
            return

        dpr = self.devicePixelRatioF() or 1.0
        transform_mode = (
            QtCore.Qt.FastTransformation
            if self._playing
            else QtCore.Qt.SmoothTransformation
        )
        if (
            not self._scale_dirty
            and self._scaled_qimage is not None
            and self._scaled_for_size == size
            and abs(self._scaled_for_dpr - dpr) < 0.01
            and self._scaled_transform_mode == transform_mode
        ):
            self._last_scale_ms = 0.0
            return

        start = time.perf_counter() if perf_enabled() else None
        image = self._frame_qimage
        if self._rotation_deg:
            transform = QtGui.QTransform()
            transform.rotate(self._rotation_deg)
            image = image.transformed(transform, transform_mode)
        target_size = QtCore.QSize(
            max(1, int(size.width() * dpr)),
            max(1, int(size.height() * dpr)),
        )
        scaled = image.scaled(
            target_size,
            QtCore.Qt.KeepAspectRatio,
            transform_mode,
        )
        scaled.setDevicePixelRatio(dpr)
        self._scaled_qimage = scaled
        self._scaled_for_size = size
        self._scaled_for_dpr = dpr
        self._scaled_transform_mode = transform_mode
        img_width = scaled.width() / dpr
        img_height = scaled.height() / dpr
        x = (self.width() - img_width) / 2.0
        y = (self.height() - img_height) / 2.0
        self._scaled_target_rect = QtCore.QRectF(x, y, img_width, img_height)
        self._scale_dirty = False
        if start is not None:
            self._last_scale_ms = (time.perf_counter() - start) * 1000.0
        else:
            self._last_scale_ms = None


class QtSnapshotRenderer:
    """Qt-native renderer using QWidget paintEvent + cached QImage."""

    def __init__(
        self,
        parent: QtWidgets.QWidget | None = None,
        *,
        cache: QImageLruCache | None = None,
    ) -> None:
        self._view = QtFrameView(parent)
        self._last_convert_ms: float | None = None
        self._last_cache_hit: bool | None = None
        self._last_cache_bytes: int | None = None
        self._last_cache_max_bytes: int | None = None
        self._cache = cache if cache is not None else QImageLruCache.from_env()
        self._rotation_deg = 0

    @property
    def widget(self) -> QtWidgets.QWidget:
        return self._view

    @property
    def last_convert_ms(self) -> float | None:
        return self._last_convert_ms

    @property
    def last_scale_ms(self) -> float | None:
        return self._view.last_scale_ms

    @property
    def last_cache_hit(self) -> bool | None:
        return self._last_cache_hit

    @property
    def cache_bytes(self) -> int | None:
        return self._last_cache_bytes

    @property
    def cache_max_bytes(self) -> int | None:
        return self._last_cache_max_bytes

    @property
    def cache(self) -> QImageLruCache | None:
        return self._cache

    def set_frame(self, frame: FrameData, frame_index: int | None = None) -> None:
        qimage = self._coerce_qimage(frame, frame_index=frame_index)
        if qimage is None:
            raise ValueError("Unsupported frame format for Qt snapshot renderer")
        self._view.set_frame(qimage, frame_index=frame_index)

    def clear(self) -> None:
        self._view.clear()
        self._last_convert_ms = None

    def set_playing(self, playing: bool) -> None:
        self._view.set_playing(playing)

    def set_rotation(self, angle_deg: int) -> None:
        self._rotation_deg = int(angle_deg) % 360
        self._view.set_rotation(angle_deg)

    def _coerce_qimage(
        self, frame: FrameData, frame_index: int | None = None
    ) -> QtGui.QImage | None:
        self._last_cache_hit = None
        cache_key = None
        if frame_index is not None and self._cache is not None:
            cache_key = qimage_cache_key(frame_index, self._rotation_deg)

        if isinstance(frame, QtGui.QImage):
            self._last_convert_ms = None
            if self._cache is not None and cache_key is not None:
                self._cache.set(cache_key, frame)
            self._update_cache_stats()
            return frame
        if isinstance(frame, QtGui.QPixmap):
            self._last_convert_ms = None
            qimage = frame.toImage()
            if self._cache is not None and cache_key is not None:
                self._cache.set(cache_key, qimage)
            self._update_cache_stats()
            return qimage
        if not isinstance(frame, np.ndarray):
            self._last_convert_ms = None
            self._update_cache_stats()
            return None

        if self._cache is not None and cache_key is not None:
            cached = self._cache.get(cache_key)
            if cached is not None:
                self._last_cache_hit = True
                self._last_convert_ms = 0.0
                self._update_cache_stats()
                return cached

        start = time.perf_counter() if perf_enabled() else None
        qimage = numpy_to_qimage(frame)
        if qimage is None:
            self._last_convert_ms = None
            self._last_cache_hit = False
            self._update_cache_stats()
            return None
        if self._cache is not None and cache_key is not None:
            self._cache.set(cache_key, qimage)
        if start is not None:
            self._last_convert_ms = (time.perf_counter() - start) * 1000.0
        else:
            self._last_convert_ms = None
        self._last_cache_hit = False
        self._update_cache_stats()
        return qimage

    def _update_cache_stats(self) -> None:
        if self._cache is None:
            self._last_cache_bytes = None
            self._last_cache_max_bytes = None
            return
        self._last_cache_bytes = self._cache.current_bytes
        self._last_cache_max_bytes = self._cache.max_bytes


__all__ = [
    "FrameData",
    "SnapshotRenderer",
    "QtFrameView",
    "QtSnapshotRenderer",
    "coerce_qimage",
    "numpy_to_qimage",
    "numpy_rgb_to_qimage",
]
