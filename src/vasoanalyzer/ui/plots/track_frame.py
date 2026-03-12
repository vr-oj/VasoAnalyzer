"""Frame wrapper for stacked tracks with structural row separators."""

from __future__ import annotations

from PyQt6.QtCore import QEvent
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QFrame, QSizePolicy, QVBoxLayout, QWidget

from vasoanalyzer.ui.theme import CURRENT_THEME

TRACK_DIVIDER_THICKNESS_PX = 2

__all__ = ["TRACK_DIVIDER_THICKNESS_PX", "TrackFrame"]


class TrackFrame(QWidget):
    """Wrap one track widget and host a structural bottom divider."""

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
        self._content_host = QWidget(self)
        self._content_layout = QVBoxLayout(self._content_host)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(0)

        self._separator_bar = QFrame(self)
        self._separator_bar.setObjectName("TrackSeparatorBar")
        self._separator_bar.setFrameShape(QFrame.Shape.NoFrame)
        self._separator_bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._layout.addWidget(self._content_host, 1)
        self._layout.addWidget(self._separator_bar, 0)
        self._apply_divider_style()
        self._refresh_divider_geometry()
        if child is not None:
            self.set_child(child)

    def set_child(self, child: QWidget) -> None:
        """Set the wrapped child widget."""
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
        child.setParent(self._content_host)
        self._content_layout.addWidget(child, 1)

    def set_divider_visible(self, visible: bool) -> None:
        self._divider_visible = bool(visible)
        self._refresh_divider_geometry()
        self._apply_divider_style()

    def divider_visible(self) -> bool:
        return bool(self._divider_visible)

    def set_divider_thickness(self, thickness: int) -> None:
        self._divider_thickness = max(int(thickness), 0)
        self._refresh_divider_geometry()
        self._apply_divider_style()

    def divider_thickness(self) -> int:
        return int(self._divider_thickness)

    def event(self, event) -> bool:  # noqa: N802 - Qt API
        handled = super().event(event)
        if event is not None and event.type() in {
            QEvent.Type.PaletteChange,
            QEvent.Type.ApplicationPaletteChange,
            QEvent.Type.StyleChange,
            QEvent.Type.Show,
        }:
            self._apply_divider_style()
        return handled

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

    def _refresh_divider_geometry(self) -> None:
        height = int(self._divider_thickness) if self._divider_visible else 0
        self._separator_bar.setFixedHeight(max(height, 0))

    def _apply_divider_style(self) -> None:
        if not self._divider_visible or self._divider_thickness <= 0:
            self._separator_bar.setStyleSheet("QFrame#TrackSeparatorBar { background: transparent; }")
            return
        color = self._divider_color()
        if not color.isValid():
            self._separator_bar.setStyleSheet("QFrame#TrackSeparatorBar { background: transparent; }")
            return
        self._separator_bar.setStyleSheet(
            f"QFrame#TrackSeparatorBar {{ background: {color.name()}; border: none; }}"
        )
