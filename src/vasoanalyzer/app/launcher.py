"""Application bootstrap utilities for the VasoAnalyzer desktop app."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from PyQt5.QtCore import QCoreApplication, QEvent, QObject, Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPixmap
from PyQt5.QtWidgets import QApplication, QMessageBox, QSplashScreen

from utils.config import APP_VERSION
from vasoanalyzer.app.window_manager import WindowManager
from vasoanalyzer.core.single_instance import (
    consume_ipc_warning,
    dispatch_pending_open_requests,
    has_pending_open_requests,
    open_project_from_path,
    queue_open_requests,
    register_window_manager,
)
from vasoanalyzer.ui import theme

try:  # Optional helper used for locating packaged resources
    from utils import resource_path
except ImportError:  # pragma: no cover - fallback when utils is absent
    resource_path = None


log = logging.getLogger(__name__)

# Ensure HiDPI scaling is enabled before the QApplication is instantiated
os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")


class _FileOpenEventFilter(QObject):
    """Handle macOS Finder file-open events."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)

    def eventFilter(self, obj, event):  # type: ignore[override]
        if event.type() == QEvent.FileOpen:
            path = event.file()
            if path:
                open_project_from_path(path)
            return True
        return super().eventFilter(obj, event)


class VasoAnalyzerLauncher:
    """Create the Qt application, theme it, and show the main window."""

    def __init__(self, project_path: str | None = None) -> None:
        self.project_path = project_path

        QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
        QCoreApplication.setApplicationName("VasoAnalyzer")

        self.app = QApplication(sys.argv)
        self._file_open_filter = _FileOpenEventFilter(self.app)
        self.app.installEventFilter(self._file_open_filter)
        if self.project_path:
            queue_open_requests([self.project_path])
        self._apply_branding()
        self._apply_theme()
        self._show_splash()

    # ------------------------------------------------------------------
    def _apply_branding(self) -> None:
        """Apply application name and platform-specific icons."""

        if sys.platform.startswith("win"):
            icon_name = "VasoAnalyzerIcon.ico"
        elif sys.platform == "darwin":
            icon_name = "VasoAnalyzerIcon.icns"
        else:
            icon_name = None

        if icon_name:
            candidate = Path(__file__).resolve().parent.parent / icon_name
            if candidate.exists():
                self.app.setWindowIcon(QIcon(str(candidate)))

    # ------------------------------------------------------------------
    def _apply_theme(self) -> None:
        """
        Apply user's preferred theme (light or dark) from settings.

        Loads the theme preference and applies it. Defaults to light theme.
        """
        try:
            # Load user's theme preference from settings
            from PyQt5.QtCore import QSettings

            settings = QSettings("TykockiLab", "VasoAnalyzer")
            mode = settings.value("appearance/themeMode", "light", type=str)

            # Apply the theme using our preset system
            theme.set_theme_mode(mode, persist=False)
        except Exception:  # pragma: no cover - very defensive fallback
            # Fallback to light theme
            theme.set_theme_mode("light", persist=False)

        # Use native OS style for better platform integration
        # Force a hard exit on macOS to avoid SIP teardown segfaults on exit.
        if sys.platform == "darwin":
            self.app.setStyle("macintosh")
        # Windows uses default style which is already native

    # ------------------------------------------------------------------
    def _show_splash(self) -> None:
        assets_root = Path(__file__).resolve().parent.parent
        splash_path = assets_root / "VasoAnalyzerSplashScreen.png"
        pixmap = QPixmap(str(splash_path))

        if pixmap.isNull():
            log.warning("Splash image missing at %s", splash_path)
            self._start_main_window()
            return
        self._draw_version_badge(pixmap)

        device_ratio = self.app.devicePixelRatio()
        target_size = int(400 * device_ratio)
        scaled = pixmap.scaled(
            target_size,
            target_size,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        scaled.setDevicePixelRatio(device_ratio)

        self.splash = QSplashScreen(scaled, Qt.WindowStaysOnTopHint)
        self.splash.setMask(scaled.mask())
        self.splash.show()

        QTimer.singleShot(0, self._start_main_window)

    # ------------------------------------------------------------------
    def _draw_version_badge(self, pixmap: QPixmap) -> None:
        """Render an overlay chip with the app version on the splash image."""

        painter = QPainter(pixmap)
        try:
            painter.setRenderHint(QPainter.Antialiasing)

            font = QFont()
            font.setPointSize(14)
            font.setBold(True)
            painter.setFont(font)

            text = APP_VERSION
            metrics = painter.fontMetrics()
            text_width, text_height = metrics.horizontalAdvance(text), metrics.height()

            pad_x, pad_y = 12, 8
            badge_width, badge_height = text_width + 2 * pad_x, text_height + 2 * pad_y
            x = pixmap.width() - badge_width - 16
            y = 16

            badge_path = QPainterPath()
            badge_path.addRoundedRect(x, y, badge_width, badge_height, 10, 10)
            painter.fillPath(badge_path, QColor(48, 104, 255, 210))

            painter.setPen(Qt.white)
            painter.drawText(x + pad_x, y + pad_y + metrics.ascent(), text)
        finally:
            painter.end()

    # ------------------------------------------------------------------
    def _start_main_window(self) -> None:
        splash = getattr(self, "splash", None)
        try:
            manager = WindowManager(self.app)
            home = manager.open_home()
            if splash:
                splash.finish(home)

            # Note: Crash recovery is handled inline when opening projects
            # (see main_window.py lines ~945 and project_mixin.py lines ~192)
            # No need for global scan of autosave files

            register_window_manager(manager)
            if consume_ipc_warning():
                QMessageBox.warning(
                    home,
                    "Single Instance Unavailable",
                    (
                        "Could not forward the open request to an existing VasoAnalyzer window.\n"
                        "If another instance is running, avoid editing the same project in both "
                        "windows to prevent corruption."
                    ),
                )
            if has_pending_open_requests():
                QTimer.singleShot(100, dispatch_pending_open_requests)
            else:
                QTimer.singleShot(100, home.show_welcome_dialog)
            self.window_manager = manager
            log.info("Home dashboard started successfully")
        except Exception:  # pragma: no cover - defensive logging for GUI
            log.exception("Error launching main window")
            if splash:
                splash.close()

    # ------------------------------------------------------------------
    def run(self) -> None:
        exit_code = self.app.exec_()
        if sys.platform == "darwin":
            try:
                logging.shutdown()
            finally:
                os._exit(exit_code)
        sys.exit(exit_code)


__all__ = ["VasoAnalyzerLauncher"]
