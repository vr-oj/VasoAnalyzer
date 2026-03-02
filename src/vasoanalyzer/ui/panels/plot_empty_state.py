"""Empty-state panel for the plot area when no dataset is loaded."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout


class PlotEmptyState(QFrame):
    """Centered empty-state panel with primary/secondary actions."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("PlotEmptyState")
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)

        self.title_label = QLabel("No data loaded", self)
        self.title_label.setObjectName("PlotEmptyStateTitle")
        self.title_label.setAlignment(Qt.AlignCenter)

        self.body_label = QLabel("Open data for a quick look, or import into this project.", self)
        self.body_label.setObjectName("PlotEmptyStateBody")
        self.body_label.setWordWrap(True)
        self.body_label.setAlignment(Qt.AlignCenter)

        self.primary_button = QPushButton("Open Data...", self)
        self.primary_button.setObjectName("PlotEmptyStatePrimaryButton")

        self.secondary_button = QPushButton("Import Folder...", self)
        self.secondary_button.setObjectName("PlotEmptyStateSecondaryButton")

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(8)
        button_row.addStretch()
        button_row.addWidget(self.primary_button)
        button_row.addWidget(self.secondary_button)
        button_row.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(10)
        layout.addWidget(self.title_label)
        layout.addWidget(self.body_label)
        layout.addLayout(button_row)

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
