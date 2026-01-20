# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Custom timeline widget for snapshot navigation."""

from PyQt5.QtCore import Qt, pyqtSignal, QRect
from PyQt5.QtGui import QPainter, QColor, QPen, QFont
from PyQt5.QtWidgets import QWidget, QSizePolicy

from vasoanalyzer.ui.theme import CURRENT_THEME


class SnapshotTimelineWidget(QWidget):
    """Custom timeline widget for snapshot navigation.

    Displays:
    - Visual progress bar showing playback position
    - Frame numbers at regular intervals
    - Timestamps (if available) below frame numbers
    - Interactive scrubber for seeking
    """

    seek_requested = pyqtSignal(int)  # Emits frame index when user seeks

    def __init__(self, parent=None):
        super().__init__(parent)
        self._frame_count = 0
        self._current_frame = 0
        self._frame_times = []  # List[float] or None
        self._dragging = False
        self._hover = False

        # Visual settings
        self.setMinimumHeight(60)
        self.setMaximumHeight(80)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMouseTracking(True)

    def set_frame_count(self, count: int) -> None:
        """Set total number of frames."""
        self._frame_count = max(0, int(count))
        self.update()

    def set_current_frame(self, index: int) -> None:
        """Update current frame position (called externally, blocks signals)."""
        if self._frame_count > 0 and 0 <= index < self._frame_count:
            self._current_frame = int(index)
            self.update()
        elif self._frame_count == 0:
            self._current_frame = 0
            self.update()

    def set_frame_times(self, times: list[float] | None) -> None:
        """Set timestamps for each frame (or None if unavailable)."""
        self._frame_times = times if times else []
        self.update()

    def paintEvent(self, event):
        """Custom painting: progress bar, labels, scrubber."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Get theme colors
        bg_color = QColor(CURRENT_THEME.get("plot_bg", "#2B2B2B"))
        text_color = QColor(CURRENT_THEME.get("text", "#FFFFFF"))
        accent_color = QColor(CURRENT_THEME.get("accent", "#00A8E8"))
        grid_color = QColor(CURRENT_THEME.get("grid_color", "#3F3F3F"))

        # Draw background
        painter.fillRect(self.rect(), bg_color)

        # Define layout regions
        width = self.width()
        height = self.height()

        frame_label_height = 18
        bar_height = 20
        timestamp_height = 16
        margin = 10

        bar_y = frame_label_height + 5
        bar_rect = QRect(margin, bar_y, width - 2 * margin, bar_height)

        # Draw progress bar background
        painter.setPen(QPen(grid_color, 1))
        painter.setBrush(bg_color.darker(120))
        painter.drawRect(bar_rect)

        # Draw progress fill
        if self._frame_count > 0:
            progress_ratio = self._current_frame / max(1, self._frame_count - 1)
            fill_width = int(bar_rect.width() * progress_ratio)
            fill_rect = QRect(bar_rect.x(), bar_rect.y(), fill_width, bar_rect.height())
            painter.setBrush(accent_color.darker(150))
            painter.drawRect(fill_rect)

            # Draw scrubber handle
            scrubber_x = bar_rect.x() + fill_width
            scrubber_y = bar_rect.center().y()
            painter.setBrush(accent_color)
            painter.setPen(QPen(text_color, 2))
            painter.drawEllipse(scrubber_x - 6, scrubber_y - 6, 12, 12)

        # Draw frame number labels
        painter.setPen(text_color)
        painter.setFont(QFont("Arial", 9))

        if self._frame_count > 0:
            # Draw current frame number
            current_text = f"Frame {self._current_frame + 1} / {self._frame_count}"
            painter.drawText(bar_rect.x(), 12, current_text)

            # Draw timestamp if available
            if self._frame_times and self._current_frame < len(self._frame_times):
                time_s = self._frame_times[self._current_frame]
                time_text = self._format_time(time_s)
                painter.setPen(text_color.darker(130))
                painter.setFont(QFont("Arial", 8))
                timestamp_y = bar_y + bar_height + 14
                painter.drawText(bar_rect.x(), timestamp_y, time_text)

        painter.end()

    def _format_time(self, seconds: float) -> str:
        """Format seconds as MM:SS.ss or HH:MM:SS.ss."""
        if not isinstance(seconds, (int, float)):
            return "—"
        if seconds < 0:
            return "—"

        total_seconds = int(seconds)
        fractional = seconds - total_seconds

        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        secs = total_seconds % 60

        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}.{int(fractional * 100):02d}"
        else:
            return f"{minutes:02d}:{secs:02d}.{int(fractional * 100):02d}"

    def mousePressEvent(self, event):
        """Start drag or jump to position."""
        if event.button() == Qt.LeftButton and self._frame_count > 0:
            self._dragging = True
            self._seek_to_position(event.x())

    def mouseMoveEvent(self, event):
        """Update scrubber during drag."""
        if self._dragging:
            self._seek_to_position(event.x())
        else:
            self.setCursor(Qt.PointingHandCursor if self._is_over_bar(event.pos()) else Qt.ArrowCursor)

    def mouseReleaseEvent(self, event):
        """Finish drag."""
        if event.button() == Qt.LeftButton:
            self._dragging = False

    def _seek_to_position(self, x: int) -> None:
        """Convert X coordinate to frame index and emit signal."""
        margin = 10
        bar_width = self.width() - 2 * margin

        if bar_width <= 0 or self._frame_count <= 0:
            return

        # Map X to frame index
        relative_x = max(0, min(x - margin, bar_width))
        ratio = relative_x / bar_width
        frame_index = int(ratio * (self._frame_count - 1))
        frame_index = max(0, min(frame_index, self._frame_count - 1))

        # Update display and emit signal
        self._current_frame = frame_index
        self.update()
        self.seek_requested.emit(frame_index)

    def _is_over_bar(self, pos) -> bool:
        """Check if mouse is over the progress bar region."""
        margin = 10
        bar_y = 23  # frame_label_height + 5
        bar_height = 20
        bar_rect = QRect(margin, bar_y, self.width() - 2 * margin, bar_height)
        return bar_rect.contains(pos)

    # QSlider compatibility methods for backward compatibility
    def setValue(self, value: int) -> None:
        """Qt slider compatibility method."""
        self.set_current_frame(value)

    def value(self) -> int:
        """Qt slider compatibility method."""
        return self._current_frame

    def setMinimum(self, minimum: int) -> None:
        """Qt slider compatibility (no-op, always 0)."""
        pass

    def setMaximum(self, maximum: int) -> None:
        """Qt slider compatibility - sets frame count."""
        self.set_frame_count(maximum + 1)  # Maximum is last index, count is +1

    def blockSignals(self, block: bool) -> bool:
        """Override to properly handle signal blocking."""
        return super().blockSignals(block)
