# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Frame rendering widget for the TIFF viewer v2."""

from __future__ import annotations

from typing import Any

import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets

from vasoanalyzer.ui import theme as theme_module

FrameData = Any


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


def _numpy_rgb_to_qimage(arr: np.ndarray) -> QtGui.QImage:
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


def numpy_to_qimage(arr: np.ndarray) -> QtGui.QImage | None:
    arr = np.asarray(arr)
    if arr.size == 0:
        return None
    if arr.ndim == 2:
        arr = _ensure_uint8(arr)
        return _numpy_gray_to_qimage(arr)
    if arr.ndim == 3:
        if arr.shape[2] == 1:
            arr = _ensure_uint8(arr[:, :, 0])
            return _numpy_gray_to_qimage(arr)
        if arr.shape[2] == 3:
            arr = _ensure_uint8(arr)
            return _numpy_rgb_to_qimage(arr)
    return None


def coerce_qimage(frame: FrameData) -> QtGui.QImage | None:
    if isinstance(frame, QtGui.QImage):
        return frame
    if isinstance(frame, QtGui.QPixmap):
        return frame.toImage()
    if isinstance(frame, np.ndarray):
        return numpy_to_qimage(frame)
    return None


def _snapshot_background_color() -> QtGui.QColor:
    try:
        current_theme = getattr(theme_module, "CURRENT_THEME", None)
        if isinstance(current_theme, dict):
            value = current_theme.get("snapshot_bg")
            if value:
                return QtGui.QColor(value)
    except Exception:
        pass
    app = QtWidgets.QApplication.instance()
    if app is not None:
        return app.palette().color(QtGui.QPalette.Window)
    return QtGui.QColor(30, 30, 30)


class FrameView(QtWidgets.QWidget):
    """Widget that paints a cached, scaled QImage with letterboxing."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._frame_qimage: QtGui.QImage | None = None
        self._scaled_qimage: QtGui.QImage | None = None
        self._scaled_for_size = QtCore.QSize()
        self._scaled_for_dpr = 1.0
        self._scaled_target_rect = QtCore.QRectF()
        self._background_color = _snapshot_background_color()
        self._transform_mode = QtCore.Qt.SmoothTransformation
        self.setAttribute(QtCore.Qt.WA_OpaquePaintEvent)

    def sizeHint(self) -> QtCore.QSize:
        if self._frame_qimage is not None and not self._frame_qimage.isNull():
            return self._frame_qimage.size()
        return QtCore.QSize(200, 150)

    def hasHeightForWidth(self) -> bool:
        return self._frame_qimage is not None and not self._frame_qimage.isNull()

    def heightForWidth(self, width: int) -> int:
        if self._frame_qimage is None or self._frame_qimage.isNull():
            return -1
        iw = self._frame_qimage.width()
        ih = self._frame_qimage.height()
        if iw <= 0:
            return -1
        return max(80, int(width * ih / iw))

    def set_frame(self, qimage: QtGui.QImage | None) -> None:
        self._frame_qimage = qimage
        self._scaled_qimage = None
        self.updateGeometry()
        self.update()

    def clear(self) -> None:
        self.set_frame(None)

    def set_background_color(self, color: QtGui.QColor) -> None:
        self._background_color = QtGui.QColor(color)
        self.update()

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self._scaled_qimage = None
        self._scaled_for_size = QtCore.QSize()
        self._scaled_target_rect = QtCore.QRectF()

    def changeEvent(self, event: QtCore.QEvent) -> None:
        if event.type() == QtCore.QEvent.PaletteChange:
            self._background_color = _snapshot_background_color()
        super().changeEvent(event)

    def _ensure_scaled(self) -> QtGui.QImage | None:
        if self._frame_qimage is None or self._frame_qimage.isNull():
            return None
        size = self.size()
        if size.isEmpty():
            return None
        dpr = float(self.devicePixelRatioF())
        if (
            self._scaled_qimage is not None
            and self._scaled_for_size == size
            and abs(self._scaled_for_dpr - dpr) < 0.01
        ):
            return self._scaled_qimage

        target = QtCore.QSize(
            max(1, int(size.width() * dpr)),
            max(1, int(size.height() * dpr)),
        )
        scaled = self._frame_qimage.scaled(target, QtCore.Qt.KeepAspectRatio, self._transform_mode)
        scaled.setDevicePixelRatio(dpr)
        self._scaled_qimage = scaled
        self._scaled_for_size = size
        self._scaled_for_dpr = dpr
        img_width = scaled.width() / dpr
        img_height = scaled.height() / dpr
        x = (self.width() - img_width) / 2.0
        y = (self.height() - img_height) / 2.0
        self._scaled_target_rect = QtCore.QRectF(x, y, img_width, img_height)
        return scaled

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), self._background_color)
        scaled = self._ensure_scaled()
        if scaled is None:
            painter.end()
            return

        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        painter.drawImage(self._scaled_target_rect, scaled)
        painter.end()


__all__ = ["FrameView", "coerce_qimage", "numpy_to_qimage"]
