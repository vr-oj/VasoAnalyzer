from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QCheckBox, QPushButton


class TutorialDialog(QDialog):
    """Simple tutorial dialog shown on first launch."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Welcome to VasoAnalyzer")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        text = (
            "<b>Getting Started</b><br>"
            "1. Use <b>📂 Load Trace + Events</b> to open your CSV trace."
            "<br>2. Zoom and pan using the toolbar buttons."
            "<br>3. Pin points to annotate or edit events."
            "<br>4. Export plots and tables from the Save menu."
        )
        label = QLabel(text)
        label.setWordWrap(True)
        layout.addWidget(label)

        self.dont_show_chk = QCheckBox("Don't show this again")
        layout.addWidget(self.dont_show_chk)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

    def exec_(self):
        super().exec_()
        return self.dont_show_chk.isChecked()
