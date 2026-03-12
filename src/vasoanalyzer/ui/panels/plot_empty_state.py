"""Empty-state panel for the plot area when no dataset is loaded."""

from __future__ import annotations

import sys

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout


def _shortcut_prefix() -> str:
    """Return the platform-appropriate modifier key label."""
    return "\u2318" if sys.platform == "darwin" else "Ctrl"


class PlotEmptyState(QFrame):
    """Centered empty-state panel with primary/secondary actions."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("PlotEmptyState")
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum)

        self.title_label = QLabel("No data loaded", self)
        self.title_label.setObjectName("PlotEmptyStateTitle")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.body_label = QLabel(
            "Open a trace file to get started, or import a folder of datasets into this project.",
            self,
        )
        self.body_label.setObjectName("PlotEmptyStateBody")
        self.body_label.setWordWrap(True)
        self.body_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.primary_button = QPushButton("Open Data\u2026", self)
        self.primary_button.setObjectName("PlotEmptyStatePrimaryButton")

        self.secondary_button = QPushButton("Import Folder\u2026", self)
        self.secondary_button.setObjectName("PlotEmptyStateSecondaryButton")

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(8)
        button_row.addStretch()
        button_row.addWidget(self.primary_button)
        button_row.addWidget(self.secondary_button)
        button_row.addStretch()

        mod = _shortcut_prefix()
        self.hint_label = QLabel(
            f"Tip: Use {mod}+O to open data, or {mod}+/ to open the Welcome Guide.",
            self,
        )
        self.hint_label.setObjectName("PlotEmptyStateHint")
        self.hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint_label.setStyleSheet("color: #888; font-size: 11px; margin-top: 6px;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(10)
        layout.addWidget(self.title_label)
        layout.addWidget(self.body_label)
        layout.addLayout(button_row)
        layout.addWidget(self.hint_label)

    def set_primary_action(self, action, *, tooltip: str | None = None) -> None:
        if action is None:
            self.primary_button.setEnabled(False)
            return
        try:
            self.primary_button.clicked.disconnect()
        except TypeError:
            pass
        self.primary_button.clicked.connect(action.trigger)
        if tooltip:
            self.primary_button.setToolTip(tooltip)

    def set_secondary_action(
        self, action, *, text: str | None = None, tooltip: str | None = None
    ) -> None:
        if action is None:
            self.secondary_button.setVisible(False)
            return
        if text:
            self.secondary_button.setText(text)
        try:
            self.secondary_button.clicked.disconnect()
        except TypeError:
            pass
        self.secondary_button.clicked.connect(action.trigger)
        if tooltip:
            self.secondary_button.setToolTip(tooltip)
