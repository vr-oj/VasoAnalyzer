"""Application bootstrap utilities for the VasoAnalyzer desktop app."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from PyQt5.QtCore import QCoreApplication, Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPixmap
from PyQt5.QtWidgets import QApplication, QSplashScreen

from utils.config import APP_VERSION
from vasoanalyzer.ui import theme
from vasoanalyzer.ui.main_window import VasoAnalyzerApp

try:  # Optional helper used for locating packaged resources
    from utils import resource_path
except ImportError:  # pragma: no cover - fallback when utils is absent
    resource_path = None


log = logging.getLogger(__name__)

# Ensure HiDPI scaling is enabled before the QApplication is instantiated
os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")


class VasoAnalyzerLauncher:
    """Create the Qt application, theme it, and show the main window."""

    def __init__(self, project_path: str | None = None) -> None:
        self.project_path = project_path

        QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
        QCoreApplication.setApplicationName("VasoAnalyzer")

        self.app = QApplication(sys.argv)
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

            text = f"v{APP_VERSION}"
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
            window = VasoAnalyzerApp()
            window.show()
            if splash:
                splash.finish(window)

            # Note: Crash recovery is handled inline when opening projects
            # (see main_window.py lines ~945 and project_mixin.py lines ~192)
            # No need for global scan of autosave files

            if self.project_path:
                QTimer.singleShot(100, lambda: window.open_recent_project(self.project_path))
            else:
                QTimer.singleShot(100, window.show_welcome_dialog)
            self.window = window
            log.info("Main window started successfully")
        except Exception:  # pragma: no cover - defensive logging for GUI
            log.exception("Error launching main window")
            if splash:
                splash.close()

    # ------------------------------------------------------------------
    def run(self) -> None:
        sys.exit(self.app.exec_())


__all__ = ["VasoAnalyzerLauncher"]
