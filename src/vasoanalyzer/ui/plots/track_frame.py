"""Frame wrapper for contiguous stacked tracks with per-track outline painting."""

from __future__ import annotations

from PyQt5.QtGui import QColor, QPainter
from PyQt5.QtWidgets import QVBoxLayout, QWidget

from vasoanalyzer.ui.theme import CURRENT_THEME

TRACK_DIVIDER_THICKNESS_PX = 2

__all__ = ["TRACK_DIVIDER_THICKNESS_PX", "TrackFrame"]


class TrackFrame(QWidget):
    """Wrap one track widget and paint a visible outline around the track."""

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

    def _divider_color(self) -> QColor:
        color_hex = CURRENT_THEME.get("plot_divider", CURRENT_THEME.get("border", None))
        if color_hex:
            color = QColor(str(color_hex))
            if color.isValid():
                return color

        bg = QColor(str(CURRENT_THEME.get("plot_bg", "#FFFFFF")))
        if not bg.isValid():
            bg = QColor("#FFFFFF")
        fg = QColor(str(CURRENT_THEME.get("text", "#000000")))
        if not fg.isValid():
            fg = QColor("#000000")
        return QColor(
            (bg.red() + fg.red()) // 2,
            (bg.green() + fg.green()) // 2,
            (bg.blue() + fg.blue()) // 2,
        )

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().paintEvent(event)
        if not self._divider_visible or self._divider_thickness <= 0:
            return
        if self.width() <= 0 or self.height() <= 0:
            return

        color = self._divider_color()
        if not color.isValid():
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        thickness = max(1, min(self._divider_thickness, self.width(), self.height()))
        width = int(self.width())
        height = int(self.height())

        # Draw a clear separator between stacked channels.
        painter.fillRect(0, max(height - thickness, 0), width, thickness, color)
        painter.end()
