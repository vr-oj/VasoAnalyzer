from __future__ import annotations

import logging
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox, QWidget

from vasoanalyzer.ui.dialogs.new_project_dialog import NewProjectDialog
from vasoanalyzer.ui.home_dashboard_window import HomeDashboardWindow
from vasoanalyzer.ui.main_window import VasoAnalyzerApp

if TYPE_CHECKING:  # pragma: no cover
    from PyQt6.QtWidgets import QMainWindow

log = logging.getLogger(__name__)


class WindowManager(QObject):
    """Own and route application windows for the multi-window architecture."""

    def __init__(
        self,
        app: QApplication | None = None,
        *,
        check_updates_on_first_window: bool = True,
    ) -> None:
        super().__init__()
        self._app = app or QApplication.instance()
        self._home_window: HomeDashboardWindow | None = None
        self._main_windows: list[VasoAnalyzerApp] = []
        self._active_main_window: VasoAnalyzerApp | None = None
        self._check_updates_on_first_window = bool(check_updates_on_first_window)
        self._update_check_consumed = False
        self._modal_in_progress = False

    @property
    def home_window(self) -> HomeDashboardWindow | None:
        return self._home_window

    @property
    def main_windows(self) -> tuple[VasoAnalyzerApp, ...]:
        return tuple(self._main_windows)

    @contextmanager
    def modal_guard(self):
        self._modal_in_progress = True
        try:
            yield
        finally:
            self._modal_in_progress = False

    def show_dashboard(self, raise_: bool = True) -> HomeDashboardWindow:
        if self._home_window is None:
            self._home_window = HomeDashboardWindow(self)
            self._home_window.installEventFilter(self)
        if raise_:
            self._raise_window(self._home_window)
        else:
            self._home_window.show()
        self._home_window.refresh_recent()
        self._home_window.update_resume_state()
        return self._home_window

    def hide_dashboard(self) -> None:
        if self._home_window is not None:
            self._home_window.hide()

    def toggle_dashboard(self) -> None:
        if self._home_window is not None and self._home_window.isVisible():
            self.hide_dashboard()
        else:
            self.show_dashboard(raise_=True)

    def open_home(self) -> HomeDashboardWindow:
        return self.show_dashboard(raise_=True)

    def open_project(self, path: str) -> VasoAnalyzerApp | None:
        if not path:
            return None

        normalized = self._normalize_path(path)
        existing = self._find_window_for_path(normalized)
        if existing is not None:
            self._raise_window(existing)
            self.hide_dashboard()
            return existing

        if not Path(normalized).exists():
            self._show_warning(
                "Project Not Found",
                f"The project file could not be found:\n{normalized}",
            )
            return None

        window = self._create_main_window()
        opened = self._open_project_in_window(window, normalized)
        if not opened:
            self._discard_main_window(window)
            return None

        self._raise_window(window)
        self._refresh_home_recent()
        self._refresh_home_resume()
        self.hide_dashboard()
        return window

    def create_new_project_via_dialog(self) -> VasoAnalyzerApp | None:
        home = self.show_dashboard(raise_=True)
        settings = getattr(home, "settings", None)
        dialog = NewProjectDialog(home, settings=settings)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None

        name = dialog.project_name()
        path = dialog.project_path()
        exp_name = dialog.experiment_name()
        if not name or not path:
            return None

        window = self._create_main_window()
        self._raise_window(window)
        created = window._create_project_from_inputs(name, path, exp_name)
        if not created:
            self._discard_main_window(window)
            return None
        self._refresh_home_recent()
        self._refresh_home_resume()
        self.hide_dashboard()
        return window

    def create_new_project(self) -> VasoAnalyzerApp | None:
        return self.create_new_project_via_dialog()

    def create_project_in_window_via_dialog(self, window: VasoAnalyzerApp) -> bool:
        if window is None:
            return False
        settings = getattr(window, "settings", None)
        dialog = NewProjectDialog(window, settings=settings)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False

        name = dialog.project_name()
        path = dialog.project_path()
        exp_name = dialog.experiment_name()
        if not name or not path:
            return False

        created = window._create_project_from_inputs(name, path, exp_name)
        if created:
            self._refresh_home_recent()
            self._refresh_home_resume()
        return created

    def open_project_via_dialog(self) -> VasoAnalyzerApp | None:
        parent = self._home_window or self.get_active_main_window()
        if parent is None:
            parent = self.show_dashboard(raise_=False)

        from PyQt6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(
            parent,
            "Open Project",
            "",
            "Vaso Projects (*.vaso);;All Files (*)",
        )
        if not path:
            return None
        window = self.open_project(path)
        if window is not None:
            self._refresh_home_recent()
        return window

    def open_data_from_home(self, parent_window: QWidget | None = None) -> None:
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QFileDialog

        parent = parent_window or self._home_window or self.get_active_main_window()
        if parent is None:
            parent = self.show_dashboard(raise_=False)

        log.info("Home Open Data: opening trace file dialog")
        with self.modal_guard():
            file_paths, _ = QFileDialog.getOpenFileNames(
                parent,
                "Select Trace File(s)",
                "",
                "CSV Files (*.csv)",
            )

        if not file_paths:
            log.info("Home Open Data: file dialog canceled")
            return

        log.info("Home Open Data: selected paths=%s", file_paths)
        window = self._get_or_create_main_window()
        if window is None:
            return
        self._raise_window(window)
        self.hide_dashboard()
        log.info("Home Open Data: raised MainWindow id=%s", id(window))

        def _dispatch_import() -> None:
            if len(file_paths) > 1:
                choice = window._prompt_merge_traces(file_paths)
                if choice == "cancel":
                    return
                trace_source = file_paths if choice == "merge" else file_paths[0]
            else:
                trace_source = file_paths[0]
            window._import_trace_events_from_paths(
                trace_source,
                source="home_dialog",
            )

        QTimer.singleShot(0, _dispatch_import)

    def import_data(self, anchor: QWidget | None = None) -> VasoAnalyzerApp | None:
        from PyQt6.QtCore import QTimer

        window = self._get_or_create_main_window()
        if window is None:
            return None
        self._raise_window(window)
        self.hide_dashboard()
        # Defer one tick so the main window is active/focused (macOS).
        if hasattr(window, "load_trace_action") and window.load_trace_action is not None:
            QTimer.singleShot(0, window.load_trace_action.trigger)
        else:
            QTimer.singleShot(0, window._handle_load_trace)
        return window

    def open_recent_session(self, path: str) -> VasoAnalyzerApp | None:
        if not path:
            return None
        window = self._get_or_create_main_window()
        if window is None:
            return None
        self._raise_window(window)
        window.load_trace_and_events(path, source="recent_session")
        self._refresh_home_recent()
        self._refresh_home_resume()
        self.hide_dashboard()
        return window

    def get_active_main_window(self) -> VasoAnalyzerApp | None:
        if self._active_main_window in self._main_windows:
            return self._active_main_window
        return self._main_windows[-1] if self._main_windows else None

    def raise_window(self, window: QMainWindow) -> None:
        self._raise_window(window)

    def eventFilter(self, obj, event):  # type: ignore[override]
        if event.type() == QEvent.Type.WindowActivate:
            if isinstance(obj, VasoAnalyzerApp) and obj in self._main_windows:
                self._active_main_window = obj
                self._refresh_home_resume()
        elif event.type() == QEvent.Type.Close:
            if obj is self._home_window:
                self._home_window = None
            elif isinstance(obj, VasoAnalyzerApp) and obj in self._main_windows:
                self._remove_main_window(obj)
        return super().eventFilter(obj, event)

    def _open_project_in_window(self, window: VasoAnalyzerApp, path: str) -> bool:
        window.open_recent_project(path)
        return getattr(window, "current_project", None) is not None

    def _create_main_window(self) -> VasoAnalyzerApp:
        should_check = self._check_updates_on_first_window and not self._update_check_consumed
        window = VasoAnalyzerApp(check_updates=should_check, window_manager=self)
        if should_check:
            self._update_check_consumed = True
        self._register_main_window(window)
        return window

    def _register_main_window(self, window: VasoAnalyzerApp) -> None:
        self._main_windows.append(window)
        window.installEventFilter(self)
        self._active_main_window = window

    def _discard_main_window(self, window: VasoAnalyzerApp) -> None:
        self._remove_main_window(window)
        if window.isVisible():
            window.close()

    def _remove_main_window(self, window: VasoAnalyzerApp) -> None:
        if window in self._main_windows:
            self._main_windows.remove(window)
        if self._active_main_window is window:
            self._active_main_window = self._main_windows[-1] if self._main_windows else None
        if not self._main_windows:
            if self._home_window is None or self._home_window.isHidden():
                self.show_dashboard(raise_=True)
        self._refresh_home_resume()

    def _get_or_create_main_window(self) -> VasoAnalyzerApp | None:
        # Use last active main window when multiple exist for deterministic routing.
        window = self.get_active_main_window()
        if window is not None:
            log.debug(
                "WindowManager: reusing existing MainWindow instance id=%s",
                id(window),
            )
            return window
        log.warning("WindowManager: creating NEW MainWindow instance")
        return self._create_main_window()

    def _find_window_for_path(self, path: str) -> VasoAnalyzerApp | None:
        target = self._canonicalize_path(path)
        for window in self._main_windows:
            candidate = getattr(window, "project_path", None)
            if not candidate:
                project = getattr(window, "current_project", None)
                candidate = getattr(project, "path", None)
            if not candidate:
                continue
            resolved = self._canonicalize_path(candidate)
            if resolved == target:
                return window
        return None

    def _raise_window(self, window: QMainWindow) -> None:
        window.show()
        window.raise_()
        window.activateWindow()

    @staticmethod
    def _normalize_path(path: str) -> str:
        try:
            return str(Path(path).expanduser().resolve(strict=False))
        except Exception:
            return str(path)

    @staticmethod
    def _canonicalize_path(path: str) -> str:
        normalized = WindowManager._normalize_path(path)
        canonical = os.path.normcase(normalized)
        if sys.platform == "darwin":
            canonical = canonical.casefold()
        return canonical

    def _refresh_home_resume(self) -> None:
        if self._home_window is not None:
            self._home_window.update_resume_state()

    def _refresh_home_recent(self) -> None:
        if self._home_window is not None:
            self._home_window.refresh_recent()

    def _show_warning(self, title: str, message: str) -> None:
        parent = self._home_window if self._home_window is not None else None
        QMessageBox.warning(parent, title, message)
