from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QDragEnterEvent, QDropEvent
from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QListWidget,
    QLineEdit,
    QStackedWidget,
    QWidget,
    QCheckBox,
)


class WelcomeDialog(QDialog):
    """Interactive welcome wizard for first launch."""

    GETTING_STARTED = 1
    CREATE_PROJECT = 2
    OPEN_PROJECT = 3
    QUICK_ANALYSIS = 4

    def __init__(self, recent_projects: list[str] | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Welcome to VasoAnalyzer")
        self.setAcceptDrops(True)

        self.project_name: str | None = None
        self.experiment_name: str | None = None
        self.selected_project: str | None = None
        self.dont_show = False

        layout = QVBoxLayout(self)
        self.stack = QStackedWidget()
        layout.addWidget(self.stack)

        # ---------- Page 0 : Quick Tour ----------
        page0 = QWidget()
        l0 = QVBoxLayout(page0)
        l0.addWidget(QLabel("<b>Welcome! Choose an option:</b>"))
        btn_start = QPushButton("Getting Started")
        btn_quick = QPushButton("Quick Analysis")
        btn_create = QPushButton("Create New Project")
        btn_open = QPushButton("Open Project")
        for btn in (btn_start, btn_quick, btn_create, btn_open):
            btn.setMinimumHeight(40)
        l0.addWidget(btn_start)
        l0.addWidget(btn_quick)
        l0.addWidget(btn_create)
        l0.addWidget(btn_open)
        self.dont_show_chk = QCheckBox("Don't show this again")
        l0.addWidget(self.dont_show_chk)
        self.stack.addWidget(page0)

        # ---------- Page 1 : Project Setup ----------
        page1 = QWidget()
        l1 = QVBoxLayout(page1)
        l1.addWidget(QLabel("<b>Project Setup</b>"))
        self.project_edit = QLineEdit()
        self.project_edit.setPlaceholderText("Project name")
        self.exp_edit = QLineEdit()
        self.exp_edit.setPlaceholderText("Experiment name (optional)")
        l1.addWidget(self.project_edit)
        l1.addWidget(self.exp_edit)
        btns1 = QHBoxLayout()
        back1 = QPushButton("Back")
        create1 = QPushButton("Create")
        btns1.addWidget(back1)
        btns1.addWidget(create1)
        l1.addLayout(btns1)
        self.stack.addWidget(page1)

        # ---------- Page 2 : Recent Projects ----------
        page2 = QWidget()
        l2 = QVBoxLayout(page2)
        l2.addWidget(QLabel("<b>Open Recent</b>"))
        self.recent_list = QListWidget()
        if recent_projects:
            for p in recent_projects[:5]:
                self.recent_list.addItem(p)
        l2.addWidget(self.recent_list)
        btns2 = QHBoxLayout()
        back2 = QPushButton("Back")
        open2 = QPushButton("Open Selected")
        btns2.addWidget(back2)
        btns2.addWidget(open2)
        l2.addLayout(btns2)
        self.stack.addWidget(page2)

        # Connections ------------------------------------------------------
        btn_start.clicked.connect(lambda: self.done(self.GETTING_STARTED))
        btn_quick.clicked.connect(lambda: self.done(self.QUICK_ANALYSIS))
        btn_create.clicked.connect(lambda: self.stack.setCurrentIndex(1))
        btn_open.clicked.connect(lambda: self.stack.setCurrentIndex(2))

        back1.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        back2.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        create1.clicked.connect(self._create_clicked)
        open2.clicked.connect(self._open_clicked)

    # ---------- Result Handlers ----------------------------------------------
    def _create_clicked(self) -> None:
        name = self.project_edit.text().strip()
        if name:
            self.project_name = name
            self.experiment_name = self.exp_edit.text().strip() or None
            self.done(self.CREATE_PROJECT)

    def _open_clicked(self) -> None:
        if self.recent_list.currentItem():
            self.selected_project = self.recent_list.currentItem().text()
        self.done(self.OPEN_PROJECT)

    # ---------- Drag and Drop ------------------------------------------------
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # pragma: no cover
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.toLocalFile().lower().endswith(".vaso"):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:  # pragma: no cover
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith(".vaso"):
                self.selected_project = path
                self.done(self.OPEN_PROJECT)
                break

    # ------------------------------------------------------------------
    def exec_(self) -> int:
        result = super().exec_()
        self.dont_show = self.dont_show_chk.isChecked()
        return result
