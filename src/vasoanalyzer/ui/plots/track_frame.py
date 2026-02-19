"""Frame wrapper for contiguous stacked tracks with internal divider painting."""

from __future__ import annotations

from PyQt5.QtGui import QPainter
from PyQt5.QtGui import QPalette
from PyQt5.QtWidgets import QVBoxLayout, QWidget

TRACK_DIVIDER_THICKNESS_PX = 2

__all__ = ["TRACK_DIVIDER_THICKNESS_PX", "TrackFrame"]


class TrackFrame(QWidget):
    """Wrap one track widget and paint an internal bottom divider line."""

    def __init__(
        self,
        child: QWidget | None = None,
        *,
        divider_thickness: int = TRACK_DIVIDER_THICKNESS_PX,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._divider_visible = True
        self._divider_thickness = max(int(divider_thickness), 0)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        if child is not None:
            self.set_child(child)

    def set_child(self, child: QWidget) -> None:
        """Set the wrapped child widget."""
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
        child.setParent(self)
        self._layout.addWidget(child, 1)

    def set_divider_visible(self, visible: bool) -> None:
        self._divider_visible = bool(visible)
        self.update()

    def divider_visible(self) -> bool:
        return bool(self._divider_visible)

    def set_divider_thickness(self, thickness: int) -> None:
        self._divider_thickness = max(int(thickness), 0)
        self.update()

    def divider_thickness(self) -> int:
        return int(self._divider_thickness)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().paintEvent(event)
        if not self._divider_visible or self._divider_thickness <= 0:
            return
        if self.width() <= 0 or self.height() <= 0:
            return

        color = self.palette().color(QPalette.Mid)
        if not color.isValid():
            color = self.palette().color(QPalette.Dark)
        if not color.isValid():
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        thickness = min(self._divider_thickness, self.height())
        y = max(self.height() - thickness, 0)
        painter.fillRect(0, y, self.width(), thickness, color)
        painter.end()
