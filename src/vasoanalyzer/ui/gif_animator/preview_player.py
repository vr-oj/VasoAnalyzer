"""Preview player widget with playback controls.

This module provides a Qt widget for previewing animations with
play/pause, scrubbing, and frame navigation controls.
"""

import numpy as np
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSlider,
    QToolButton, QSizePolicy,
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QPixmap, QImage, QIcon


class PreviewPlayerWidget(QWidget):
    """Preview widget with playback controls for animated frames."""

    # Signal emitted when user scrubs to a different frame
    frame_changed = pyqtSignal(int)

    def __init__(self, parent=None):
        """Initialize preview player widget.

        Args:
            parent: Parent QWidget
        """
        super().__init__(parent)

        # State
        self.frames: list[np.ndarray] = []
        self.current_frame_idx = 0
        self.is_playing = False
        self.fps = 10

        # UI components
        self._init_ui()

        # Playback timer
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._advance_frame)

    def _init_ui(self):
        """Initialize UI components."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Frame display area
        self.frame_label = QLabel()
        self.frame_label.setAlignment(Qt.AlignCenter)
        self.frame_label.setMinimumSize(400, 300)
        self.frame_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.frame_label.setStyleSheet("QLabel { background-color: #2b2b2b; }")
        layout.addWidget(self.frame_label)

        # Controls layout
        controls_layout = QVBoxLayout()

        # Slider for scrubbing
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setMinimum(0)
        self.slider.setMaximum(0)
        self.slider.setValue(0)
        self.slider.valueChanged.connect(self._on_slider_changed)
        controls_layout.addWidget(self.slider)

        # Buttons and frame counter
        button_layout = QHBoxLayout()

        # Play/Pause button
        self.play_pause_btn = QToolButton()
        self.play_pause_btn.setText("▶")  # Play symbol
        self.play_pause_btn.setFixedSize(40, 30)
        self.play_pause_btn.clicked.connect(self._toggle_playback)
        button_layout.addWidget(self.play_pause_btn)

        # Frame counter label
        self.frame_counter_label = QLabel("Frame 0 / 0")
        self.frame_counter_label.setMinimumWidth(120)
        button_layout.addWidget(self.frame_counter_label)

        button_layout.addStretch()

        controls_layout.addLayout(button_layout)
        layout.addLayout(controls_layout)

        # Initial empty state
        self._display_empty_state()

    def load_frames(self, frames: list[np.ndarray], fps: int):
        """Load rendered frames for preview.

        Args:
            frames: List of RGB numpy arrays (H, W, 3), dtype uint8
            fps: Frames per second for playback
        """
        self.frames = frames
        self.fps = fps
        self.current_frame_idx = 0
        self.is_playing = False

        if not frames:
            self._display_empty_state()
            return

        # Update slider range
        self.slider.setMaximum(len(frames) - 1)
        self.slider.setValue(0)

        # Update timer interval
        self.timer.setInterval(int(1000 / fps))

        # Display first frame
        self._display_frame(0)

    def _display_frame(self, idx: int):
        """Display the frame at given index.

        Args:
            idx: Frame index (0-based)
        """
        if not self.frames or idx < 0 or idx >= len(self.frames):
            return

        self.current_frame_idx = idx

        # Convert numpy array to QPixmap
        frame = self.frames[idx]
        pixmap = self._numpy_to_pixmap(frame)

        # Scale to fit label while preserving aspect ratio
        scaled_pixmap = pixmap.scaled(
            self.frame_label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )

        self.frame_label.setPixmap(scaled_pixmap)

        # Update frame counter
        self.frame_counter_label.setText(f"Frame {idx + 1} / {len(self.frames)}")

        # Update slider position (without triggering valueChanged)
        self.slider.blockSignals(True)
        self.slider.setValue(idx)
        self.slider.blockSignals(False)

    def _display_empty_state(self):
        """Display empty state when no frames loaded."""
        self.frame_label.clear()
        self.frame_label.setText("No preview available\n\nSelect events and click Refresh Preview")
        self.frame_counter_label.setText("Frame 0 / 0")
        self.slider.setMaximum(0)
        self.slider.setValue(0)

    def _numpy_to_pixmap(self, arr: np.ndarray) -> QPixmap:
        """Convert RGB numpy array to QPixmap.

        Args:
            arr: Numpy array of shape (H, W, 3), dtype uint8

        Returns:
            QPixmap containing the image
        """
        h, w, c = arr.shape
        bytes_per_line = c * w
        qimg = QImage(arr.data, w, h, bytes_per_line, QImage.Format_RGB888)
        return QPixmap.fromImage(qimg)

    def _toggle_playback(self):
        """Toggle between play and pause."""
        if self.is_playing:
            self._pause()
        else:
            self._play()

    def _play(self):
        """Start playback."""
        if not self.frames:
            return

        self.is_playing = True
        self.play_pause_btn.setText("⏸")  # Pause symbol
        self.timer.start()

    def _pause(self):
        """Pause playback."""
        self.is_playing = False
        self.play_pause_btn.setText("▶")  # Play symbol
        self.timer.stop()

    def _advance_frame(self):
        """Advance to next frame (called by timer)."""
        if not self.frames:
            return

        next_idx = self.current_frame_idx + 1
        if next_idx >= len(self.frames):
            next_idx = 0  # Loop back to start

        self._display_frame(next_idx)
        self.frame_changed.emit(next_idx)

    def _on_slider_changed(self, value: int):
        """Handle slider value change (user scrubbing).

        Args:
            value: New slider value (frame index)
        """
        # Pause playback when user manually scrubs
        if self.is_playing:
            self._pause()

        self._display_frame(value)
        self.frame_changed.emit(value)

    def clear(self):
        """Clear all frames and reset to empty state."""
        self.frames = []
        self.current_frame_idx = 0
        self.is_playing = False
        self.timer.stop()
        self._display_empty_state()

    def get_current_frame_index(self) -> int:
        """Get the currently displayed frame index.

        Returns:
            Current frame index (0-based), or -1 if no frames loaded
        """
        if not self.frames:
            return -1
        return self.current_frame_idx
