from __future__ import annotations

import logging
from typing import Callable

from PyQt5.QtCore import QPointF, Qt
from PyQt5.QtGui import (
    QColor,
    QImage,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPixmap,
    QWheelEvent,
)
from PyQt5.QtWidgets import QApplication, QWidget

log = logging.getLogger(__name__)


class PreviewViewport(QWidget):
    """Preview widget that scales the rendered figure image to fit without clipping."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._img: QImage | None = None
        self._scale_cb: Callable[[float], None] | None = None
        self._event_target: QWidget | None = None
        self._last_scale: float | None = None
        self._last_offset_x: float = 0.0
        self._last_offset_y: float = 0.0
        self._log_next_paint: bool = False
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)

    def set_image(self, image: QImage | None) -> None:
        self._img = image
        self._log_next_paint = True
        self.update()

    def set_scale_callback(self, cb: Callable[[float], None] | None) -> None:
        self._scale_cb = cb

    def set_event_target(self, target: QWidget | None) -> None:
        self._event_target = target

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().window())
        img = self._img
        if img is None or img.isNull():
            if self._log_next_paint:
                log.info(
                    "Preview paint skipped: no image widget=%sx%s",
                    self.width(),
                    self.height(),
                )
                self._log_next_paint = False
            if self._scale_cb:
                self._scale_cb(1.0)
            return

        dpr = float(self.devicePixelRatioF())
        pane_w = max(1.0, self.width() * dpr)
        pane_h = max(1.0, self.height() * dpr)
        img_w = float(img.width())
        img_h = float(img.height())
        scale = min(pane_w / img_w, pane_h / img_h, 1.0)
        dst_w = img_w * scale
        dst_h = img_h * scale
        x = (pane_w - dst_w) * 0.5
        y = (pane_h - dst_h) * 0.5

        self._last_scale = scale
        self._last_offset_x = x
        self._last_offset_y = y
        if self._scale_cb:
            self._scale_cb(scale)
        if self._log_next_paint:
            log.info(
                "Preview paint: widget=%sx%s pane=%.1fx%.1f img=%sx%s scale=%.4f offsets=(%.1f, %.1f)",
                self.width(),
                self.height(),
                pane_w,
                pane_h,
                img_w,
                img_h,
                scale,
                x,
                y,
            )
            self._log_next_paint = False

        pix = QPixmap.fromImage(img)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.drawPixmap(
            int(x / dpr),
            int(y / dpr),
            int(dst_w / dpr),
            int(dst_h / dpr),
            pix,
        )

    # Forward mouse/wheel events to the Matplotlib canvas so tools like box select keep working.
    def _forward_event(self, evt) -> None:
        target = self._event_target
        if target is None or self._img is None or self._img.isNull():
            return
        dpr = float(self.devicePixelRatioF())
        tgt_dpr = float(target.devicePixelRatioF()) if hasattr(target, "devicePixelRatioF") else 1.0
        pos = evt.position() if hasattr(evt, "position") else QPointF(evt.x(), evt.y())
        dev_x = pos.x() * dpr
        dev_y = pos.y() * dpr
        scale = self._last_scale or 1.0
        x0 = self._last_offset_x
        y0 = self._last_offset_y
        dst_w = self._img.width() * scale
        dst_h = self._img.height() * scale
        if not (x0 <= dev_x <= x0 + dst_w and y0 <= dev_y <= y0 + dst_h):
            return
        src_x = (dev_x - x0) / scale
        src_y = (dev_y - y0) / scale
        mapped = QPointF(src_x / tgt_dpr, src_y / tgt_dpr)

        if isinstance(evt, QMouseEvent):
            forwarded = QMouseEvent(
                evt.type(),
                mapped,
                mapped,
                evt.button(),
                evt.buttons(),
                evt.modifiers(),
            )
            QApplication.sendEvent(target, forwarded)
        elif isinstance(evt, QWheelEvent):
            forwarded = QWheelEvent(
                mapped,
                mapped,
                evt.pixelDelta(),
                evt.angleDelta(),
                evt.buttons(),
                evt.modifiers(),
                evt.phase(),
                evt.inverted(),
                evt.source(),
            )
            QApplication.sendEvent(target, forwarded)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self._forward_event(event)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self._forward_event(event)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._forward_event(event)
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        self._forward_event(event)
        super().wheelEvent(event)
