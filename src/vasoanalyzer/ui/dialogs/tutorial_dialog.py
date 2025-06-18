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
            "<b>Welcome to VasoAnalyzer!</b><br>"
            "This short guide will have you loading and analyzing your first experiment in under 2 minutes."
            "<br><br>"
            "1. <b>Create Your Project</b>"
            "<br>• Click <b>Create Project</b>."
            "<br>• Give your study a name (e.g., “Histamine Dose-Response”)."
            "<br><br>"
            "2. <b>Name Your First Experiment</b>"
            "<br>• In the same dialog, enter an experiment name (e.g., “Replicate 1”)."
            "<br>• Click <b>Finish</b> to open the main window."
            "<br><br>"
            "3. <b>Add Your Data</b>"
            "<br>• Select your experiment in the left sidebar."
            "<br>• Click the <b>+ Data</b> button in the toolbar."
            "<br>• Load your <b>Trace</b> and <b>Event</b> files (TIFF images are optional)."
            "<br><br>"
            "4. <b>Explore & Tag Events</b>"
            "<br>• Click directly on the trace to tag an event—you’ll see your new entry appear in the table below the image."
            "<br>• Hover or click along the plot to see synced TIFF frames in the viewer."
            "<br><br>"
            "5. <b>Customize Your View</b>"
            "<br>• Zoom and pan the plot by click-dragging on the axes."
            "<br>• Go to <b>View → Plot Style</b> to adjust axis labels, fonts, and line styles."
            "<br>• Drag the splitter bars to resize the trace, image viewer, and table."
            "<br><br>"
            "6. <b>Save & Pick Up Later</b>"
            "<br>• Click the <b>Save</b> icon (or press ⌘ S) to store both your data <b>and</b> exactly how you’ve arranged the window."
            "<br>• Tomorrow, choose <b>Open Project</b> (or select from your Recent Projects list) to return right where you left off."
            "<br><br>"
            "👍 <b>Tip:</b> Hit F1 or go to <b>Help → User Manual</b> anytime for full details on every feature."
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
