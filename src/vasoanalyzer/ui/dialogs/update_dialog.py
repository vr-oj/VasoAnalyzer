# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Update notification dialog with remind later and don't show options."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)


class UpdateDialog(QDialog):
    """Dialog shown when a new version is available."""

    # Return codes to indicate user's choice
    REMIND_LATER = 1
    DONT_SHOW = 2
    OK = 0

    def __init__(self, current_version: str, latest_version: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Update Available")
        self.resize(450, 200)

        # Store the user's choice
        self.user_choice = self.OK

        # Main layout
        main = QVBoxLayout(self)
        main.setContentsMargins(20, 20, 20, 20)
        main.setSpacing(16)

        # Title
        title = QLabel("New Version Available!")
        title.setFont(QFont("Arial", 16, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        main.addWidget(title)

        # Message
        message = QLabel(
            f"A new version ({latest_version}) of VasoAnalyzer is available!\n\n"
            f"You are currently using version {current_version}.\n"
            "Visit GitHub to download the latest release."
        )
        message.setWordWrap(True)
        message.setAlignment(Qt.AlignCenter)
        main.addWidget(message)

        main.addStretch()

        # Button layout
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)

        # Don't Show Again button
        dont_show_btn = QPushButton("Don't Show Again")
        dont_show_btn.setToolTip("Hide update notifications permanently")
        dont_show_btn.clicked.connect(self._dont_show_again)
        button_layout.addWidget(dont_show_btn)

        button_layout.addStretch()

        # Remind Later button
        remind_btn = QPushButton("Remind Me Later")
        remind_btn.setToolTip("Remind me in 7 days")
        remind_btn.clicked.connect(self._remind_later)
        button_layout.addWidget(remind_btn)

        # OK button
        ok_btn = QPushButton("OK")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self.accept)
        button_layout.addWidget(ok_btn)

        main.addLayout(button_layout)

    def _remind_later(self):
        """User chose to be reminded later."""
        self.user_choice = self.REMIND_LATER
        self.accept()

    def _dont_show_again(self):
        """User chose to never see update notifications."""
        self.user_choice = self.DONT_SHOW
        self.accept()

    def exec_(self):
        """Override exec_ to return the user's choice."""
        super().exec_()
        return self.user_choice
