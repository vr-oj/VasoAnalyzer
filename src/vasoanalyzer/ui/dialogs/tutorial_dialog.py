# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class TutorialDialog(QDialog):
    """Simple tutorial dialog shown on first launch."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Welcome to VasoAnalyzer")
        self.resize(500, 400)

        # 1) Main layout
        main = QVBoxLayout(self)
        main.setContentsMargins(16, 16, 16, 16)
        main.setSpacing(12)

        # 2) Scroll area containing step groups
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(12)

        steps = [
            (
                "1. Create Your Project",
                [
                    "Click <b>Create Project</b>.",
                    'Give your study a name (e.g., "Histamine Dose-Response").',
                ],
            ),
            (
                "2. Name Your First Experiment",
                [
                    'Enter an experiment name, such as "Concentration Response".',
                    "Click <b>Finish</b> to open the main window.",
                ],
            ),
            (
                "3. Add Your Data",
                [
                    "Select your experiment in the left sidebar.",
                    "Click the <b>Load Trace + Event</b> button in the toolbar.",
                    "Load your <b>Trace</b> and <b>Event</b> files (TIFF images are optional).",
                ],
            ),
            (
                "4. Explore & Tag Events",
                [
                    "Click directly on the trace to tag an event.",
                    "Right-click on the tag to add a new event to the table.",
                    "Hover or click along the plot to see synced TIFF frames.",
                ],
            ),
            (
                "5. Customize Your View",
                [
                    "Zoom and pan by click-dragging on the axes.",
                    "Go to View → Plot Style to adjust labels, fonts, and line styles.",
                ],
            ),
            (
                "6. Save & Pick Up Later",
                [
                    "Click the Save icon (or press ⌘ S) to store both data & layout.",
                    "Later, choose Open Project to return exactly where you left off.",
                ],
            ),
        ]

        for title, bullets in steps:
            hdr = QLabel(title)
            hdr.setFont(QFont("Arial", 16, QFont.Bold))
            vbox.addWidget(hdr)

            for b in bullets:
                lbl = QLabel(f"• {b}")
                lbl.setTextFormat(Qt.RichText)
                lbl.setWordWrap(True)
                lbl.setIndent(12)
                vbox.addWidget(lbl)

            sep = QFrame()
            sep.setFrameShape(QFrame.HLine)
            sep.setFrameShadow(QFrame.Sunken)
            vbox.addWidget(sep)

        container.setLayout(vbox)
        scroll.setWidget(container)
        main.addWidget(scroll)

        # 3) Footer with "Don't show" + Close
        footer = QHBoxLayout()
        self.dont_show_chk = QCheckBox("Don't show this again")
        footer.addWidget(self.dont_show_chk)
        footer.addStretch()
        close_btn = QPushButton("Back")
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)
        main.addLayout(footer)

    def exec_(self):
        super().exec_()
        return self.dont_show_chk.isChecked()
