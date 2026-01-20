from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING, Callable

from PyQt5.QtCore import QSettings, QSize, Qt
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from vasoanalyzer.ui.dialogs.welcome_dialog import WelcomeGuideDialog
from vasoanalyzer.ui.panels.home_page import HomePage
from vasoanalyzer.ui.theme import CURRENT_THEME

if TYPE_CHECKING:  # pragma: no cover
    from vasoanalyzer.app.window_manager import WindowManager

ONBOARDING_SETTINGS_ORG = "VasoAnalyzer"
ONBOARDING_SETTINGS_APP = "VasoAnalyzer"


def _onboarding_needed(settings: QSettings) -> bool:
    raw = settings.value("ui/show_welcome", None)
    if raw is not None:
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            return raw.strip().lower() in {"true", "1", "yes", "on"}
        try:
            return bool(int(raw))
        except Exception:
            return bool(raw)

    show_value = str(settings.value("general/show_onboarding", "true")).lower()
    return show_value in {"true", "1", "yes", "on"}


class HomeDashboardWindow(QMainWindow):
    """Top-level window that hosts the HomePage dashboard."""

    def __init__(self, window_manager: WindowManager) -> None:
        super().__init__()
        self._window_manager = window_manager
        self.settings = QSettings("TykockiLab", "VasoAnalyzer")
        self.onboarding_settings = QSettings(
            ONBOARDING_SETTINGS_ORG, ONBOARDING_SETTINGS_APP
        )
        self.recent_files: list[str] = []
        self.recent_projects: list[str] = []
        self._welcome_dialog = None
        self._onboarding_checked = False

        self._apply_window_branding()
        self.setWindowTitle("VasoAnalyzer Home")
        self.resize(1100, 700)

        self.home_page = HomePage(self)
        self.home_page.create_project_requested.connect(
            self._window_manager.create_new_project_via_dialog
        )
        self.setCentralWidget(self.home_page)

        self.load_recent_files()
        self.load_recent_projects()
        self.refresh_recent()
        self.update_resume_state()

    # ------------------------------------------------------------------
    def refresh_recent(self) -> None:
        self.load_recent_files()
        self.load_recent_projects()
        self._refresh_home_recent()

    def update_resume_state(self) -> None:
        self._update_home_resume_button()

    # ------------------------------------------------------------------
    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.refresh_recent()
        self.update_resume_state()

    # ------------------------------------------------------------------
    def _apply_window_branding(self) -> None:
        icon_ext = "svg"
        if os.name == "nt":
            icon_ext = "ico"
        elif sys.platform == "darwin":
            icon_ext = "icns"

        icon_path = self._brand_icon_path(icon_ext)
        if icon_path:
            self.setWindowIcon(QIcon(icon_path))

    # ---- HomePage actions --------------------------------------------
    def open_project_file(self, path: str | bool | None = None):
        if isinstance(path, bool):
            path = None
        if path is None:
            return self._window_manager.open_project_via_dialog()
        window = self._window_manager.open_project(path)
        if window is not None:
            self.refresh_recent()
        return window

    def home_open_project(self) -> None:
        self.open_project_file()

    def new_project(self, checked: bool = False):
        return self._window_manager.create_new_project_via_dialog()

    def home_open_data(self) -> None:
        self._window_manager.open_data_from_home(self)

    def show_import_data_menu(
        self, checked: bool = False, anchor: QWidget | None = None
    ) -> None:
        self._window_manager.open_data_from_home(self)

    def show_analysis_workspace(self):
        window = self._window_manager.get_active_main_window()
        if window is not None:
            self._window_manager.raise_window(window)

    def show_welcome_dialog(self) -> None:
        self._maybe_run_onboarding()

    def show_welcome_guide(self, modal: bool = False) -> None:
        if modal:
            dlg = WelcomeGuideDialog(self)
            dlg.openRequested.connect(self.open_project_file)
            dlg.createRequested.connect(self.new_project)
            dlg.setWindowModality(Qt.ApplicationModal)
            dlg.finished.connect(lambda _: self._handle_welcome_guide_closed(dlg))
            dlg.exec_()
            return

        existing = getattr(self, "_welcome_dialog", None)
        if existing and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            return

        dlg = WelcomeGuideDialog(self)
        dlg.openRequested.connect(self.open_project_file)
        dlg.createRequested.connect(self.new_project)
        dlg.finished.connect(lambda _: self._handle_welcome_guide_closed(dlg))
        dlg.show()
        self._welcome_dialog = dlg

    # ---- recent lists -------------------------------------------------
    def load_recent_files(self):
        recent = self.settings.value("recentFiles", [])
        self.recent_files = recent or []

    def load_recent_projects(self):
        recent = self.settings.value("recentProjects", [])
        self.recent_projects = recent or []

    def save_recent_files(self):
        self.settings.setValue("recentFiles", self.recent_files)

    def save_recent_projects(self):
        self.settings.setValue("recentProjects", self.recent_projects)

    def update_recent_projects(self, path: str) -> None:
        if path not in self.recent_projects:
            self.recent_projects = [path] + self.recent_projects[:4]
            self.settings.setValue("recentProjects", self.recent_projects)
        self._refresh_home_recent()

    def remove_recent_project(self, path: str) -> None:
        if path not in self.recent_projects:
            return
        self.recent_projects = [p for p in self.recent_projects if p != path]
        self.save_recent_projects()
        self._refresh_home_recent()

    def clear_recent_projects(self, checked: bool = False):
        self.recent_projects = []
        self.save_recent_projects()
        self._refresh_home_recent()

    def remove_recent_file(self, path: str) -> None:
        if path not in self.recent_files:
            return
        self.recent_files = [p for p in self.recent_files if p != path]
        self.save_recent_files()
        self._refresh_home_recent()

    def clear_recent_files(self, checked: bool = False):
        self.recent_files = []
        self.save_recent_files()
        self._refresh_home_recent()

    def open_recent_project(self, path: str):
        return self._window_manager.open_project(path)

    # ---- Home layout helpers -----------------------------------------
    @staticmethod
    def _clear_layout(layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _add_home_placeholder(
        self,
        layout: QVBoxLayout,
        message: str,
        button_text: str | None = None,
        callback: Callable[[], None] | None = None,
        icon_name: str = "folder-open.svg",
    ) -> None:
        placeholder = QLabel(message)
        placeholder.setObjectName("CardPlaceholder")
        placeholder.setWordWrap(True)
        layout.addWidget(placeholder)
        if button_text and callback:
            button = self._make_home_button(
                button_text,
                icon_name,
                callback,
                primary=True,
            )
            layout.addWidget(button)

    def _make_home_recent_row(
        self, label: str, path: str, open_callback, remove_callback
    ) -> QWidget:
        row = QWidget()
        row.setObjectName("HomeRecentRow")
        row.setToolTip(path)
        row.setCursor(Qt.PointingHandCursor)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        def _row_click(event):
            if event.button() == Qt.LeftButton:
                open_callback()
            event.accept()

        row.mousePressEvent = _row_click

        open_btn = QPushButton(label)
        open_btn.setProperty("isGhost", True)
        open_btn.setMinimumHeight(32)
        open_btn.setToolTip(path)
        open_btn.clicked.connect(lambda _checked=False: open_callback())
        self._apply_button_style(open_btn)
        row_layout.addWidget(open_btn, 1)

        remove_btn = QToolButton()
        remove_btn.setObjectName("HomeRemoveButton")
        remove_btn.setAutoRaise(True)
        remove_btn.setCursor(Qt.PointingHandCursor)
        remove_btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        remove_btn.setText("Remove")
        remove_btn.setToolTip(f"Remove {path}")
        remove_btn.clicked.connect(lambda _checked=False: remove_callback())
        row_layout.addWidget(remove_btn, 0, Qt.AlignRight)

        return row

    def _refresh_home_recent(self) -> None:
        if hasattr(self, "home_recent_sessions_layout"):
            layout = self.home_recent_sessions_layout
            self._clear_layout(layout)
            paths = [p for p in (self.recent_files or []) if isinstance(p, str) and p]
            has_sessions = bool(paths)
            if hasattr(self, "home_clear_sessions_button"):
                self.home_clear_sessions_button.setVisible(has_sessions)
                self.home_clear_sessions_button.setEnabled(has_sessions)
            if not has_sessions:
                self._add_home_placeholder(
                    layout,
                    "No recent imports yet. Open data to see them listed here.",
                )
            else:
                for path in paths[:3]:
                    name = os.path.basename(path) or path
                    row = self._make_home_recent_row(
                        name,
                        path,
                        lambda checked=False, p=path: self._window_manager.open_recent_session(
                            p
                        ),
                        lambda checked=False, p=path: self.remove_recent_file(p),
                    )
                    layout.addWidget(row)
            layout.addStretch()

        if hasattr(self, "home_recent_projects_layout"):
            layout = self.home_recent_projects_layout
            self._clear_layout(layout)
            projects = [
                p for p in (self.recent_projects or []) if isinstance(p, str) and p
            ]
            has_projects = bool(projects)
            if hasattr(self, "home_clear_projects_button"):
                self.home_clear_projects_button.setVisible(has_projects)
                self.home_clear_projects_button.setEnabled(has_projects)
            if not has_projects:
                self._add_home_placeholder(
                    layout,
                    "No recent projects yet. Open or create a project to see it here.",
                    "Open project…",
                    self.open_project_file,
                    "folder-open.svg",
                )
            else:
                for path in projects[:3]:
                    name = os.path.basename(path) or path
                    row = self._make_home_recent_row(
                        name,
                        path,
                        lambda checked=False, p=path: self.open_recent_project(p),
                        lambda checked=False, p=path: self.remove_recent_project(p),
                    )
                    layout.addWidget(row)
            layout.addStretch()

        self._update_home_resume_button()

    def _update_home_resume_button(self) -> None:
        if not hasattr(self, "home_resume_btn"):
            return

        active_window = self._window_manager.get_active_main_window()
        has_session = active_window is not None
        self.home_resume_btn.setVisible(has_session)
        self.home_resume_btn.setEnabled(has_session)

        tooltip = "Return to workspace"
        if active_window is not None:
            title = active_window.windowTitle()
            if title:
                tooltip = f"Return to workspace · {title}"
        self.home_resume_btn.setToolTip(tooltip)

        if hasattr(self, "home_page") and self.home_page is not None:
            self.home_page._update_responsive_layout()

    # ---- shared styling helpers --------------------------------------
    def _make_home_button(
        self,
        text: str,
        icon_name: str,
        callback,
        *,
        primary: bool = False,
        secondary: bool = False,
    ) -> QPushButton:
        button = QPushButton(text)
        button.setCursor(Qt.PointingHandCursor)
        button.setMinimumHeight(44)
        if icon_name:
            button.setIcon(QIcon(self.icon_path(icon_name)))
            button.setIconSize(QSize(20, 20))
        if primary:
            button.setProperty("isPrimary", True)
        elif secondary:
            button.setProperty("isSecondary", True)
        else:
            button.setProperty("isGhost", True)
        button.clicked.connect(lambda _checked=False: callback())
        self._apply_button_style(button)
        return button

    @staticmethod
    def _apply_button_style(button: QPushButton) -> None:
        button.style().unpolish(button)
        button.style().polish(button)

    def _shared_button_css(self) -> str:
        border = CURRENT_THEME["grid_color"]
        text = CURRENT_THEME["text"]
        button_bg = CURRENT_THEME.get("button_bg", CURRENT_THEME["window_bg"])
        button_hover_bg = CURRENT_THEME.get(
            "button_hover_bg", CURRENT_THEME.get("selection_bg", button_bg)
        )
        button_active_bg = CURRENT_THEME.get("button_active_bg", button_hover_bg)
        accent = CURRENT_THEME.get("accent", button_active_bg)
        accent_hover = CURRENT_THEME.get("accent_fill", accent)
        button_bg = CURRENT_THEME.get("button_bg", CURRENT_THEME["window_bg"])
        primary_bg = accent
        primary_hover = accent_hover
        primary_text = "#ffffff"
        secondary_bg = button_bg
        secondary_hover = button_hover_bg
        return f"""
QPushButton[isPrimary="true"] {{
    background-color: {primary_bg};
    color: {primary_text};
    border: 2px solid {primary_bg};
    border-radius: 10px;
    padding: 8px 20px;
    font-weight: 600;
}}
QPushButton[isPrimary="true"]:hover {{
    background-color: {primary_hover};
    border: 2px solid {primary_hover};
}}
QPushButton[isPrimary="true"]:pressed {{
    background-color: {button_active_bg};
    border: 2px solid {button_active_bg};
    padding: 9px 20px 7px 20px;
}}
QPushButton[isSecondary="true"] {{
    background-color: {secondary_bg};
    color: {text};
    border: 1px solid {border};
    border-radius: 10px;
    padding: 8px 20px;
    font-weight: 500;
}}
QPushButton[isSecondary="true"]:hover {{
    background-color: {secondary_hover};
    border: 2px solid {border};
    padding: 7px 19px;
}}
QPushButton[isSecondary="true"]:pressed {{
    background-color: {button_active_bg};
    border: 2px solid {border};
    padding: 8px 19px 6px 19px;
}}
QPushButton[isGhost="true"] {{
    background-color: transparent;
    color: {text};
    border: 1px solid {border};
    border-radius: 10px;
    padding: 8px 20px;
}}
QPushButton[isGhost="true"]:hover {{
    background-color: {button_hover_bg};
    border: 2px solid {border};
    padding: 7px 19px;
}}
QPushButton[isGhost="true"]:pressed {{
    background-color: {button_active_bg};
    border: 2px solid {border};
    padding: 8px 19px 6px 19px;
}}
"""

    # ---- resource helpers -------------------------------------------
    def icon_path(self, filename):
        from utils import resource_path
        from vasoanalyzer.ui import theme as theme_module

        try:
            current_theme = getattr(theme_module, "CURRENT_THEME", None)
            is_dark = False
            if isinstance(current_theme, dict):
                is_dark = bool(current_theme.get("is_dark", False))
            dark_theme = getattr(theme_module, "DARK_THEME", None)
            if (
                is_dark
                or (
                    current_theme is not None
                    and dark_theme is not None
                    and current_theme is dark_theme
                )
            ):
                name, ext = os.path.splitext(filename)
                dark_filename = f"{name}_Dark{ext}"
                candidate = resource_path("icons", dark_filename)
                if os.path.exists(candidate):
                    return candidate
        except Exception:
            pass

        return resource_path("icons", filename)

    def _brand_icon_path(self, extension: str) -> str:
        from utils import resource_path

        if not extension:
            return ""

        filename = f"VasoAnalyzerIcon.{extension}"
        search_roots = [
            ("icons", filename),
            ("vasoanalyzer", filename),
            ("src", "vasoanalyzer", filename),
        ]

        for parts in search_roots:
            candidate = resource_path(*parts)
            if os.path.exists(candidate):
                return candidate

        return ""

    # ---- onboarding helpers -----------------------------------------
    def _maybe_run_onboarding(self) -> None:
        if getattr(self, "_onboarding_checked", False):
            return
        self._onboarding_checked = True
        if _onboarding_needed(self.onboarding_settings):
            self.show_welcome_guide(modal=False)

    def _handle_welcome_guide_closed(self, dialog: WelcomeGuideDialog) -> None:
        hide = bool(getattr(dialog, "hide_for_version", False))

        self.onboarding_settings.setValue("ui/show_welcome", not hide)
        self.onboarding_settings.setValue(
            "general/show_onboarding", "false" if hide else "true"
        )

        if getattr(self, "_welcome_dialog", None) is dialog:
            self._welcome_dialog = None
