from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QListWidget

class WelcomeDialog(QDialog):
    GETTING_STARTED = 1
    CREATE_PROJECT = 2
    OPEN_PROJECT = 3

    def __init__(self, recent_projects=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Welcome to VasoAnalyzer")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<b>Welcome! Choose an option:</b>"))

        btn_start = QPushButton("Getting Started")
        btn_create = QPushButton("Create Project / Experiment")
        btn_open = QPushButton("Open Project")
        layout.addWidget(btn_start)
        layout.addWidget(btn_create)
        layout.addWidget(btn_open)

        self.recent_list = None
        if recent_projects:
            self.recent_list = QListWidget()
            for p in recent_projects:
                self.recent_list.addItem(p)
            layout.addWidget(self.recent_list)
        self.selected_project = None

        btn_start.clicked.connect(lambda: self.done(self.GETTING_STARTED))
        btn_create.clicked.connect(lambda: self.done(self.CREATE_PROJECT))
        btn_open.clicked.connect(self._open_clicked)

    def _open_clicked(self):
        if self.recent_list and self.recent_list.currentItem():
            self.selected_project = self.recent_list.currentItem().text()
        self.done(self.OPEN_PROJECT)
