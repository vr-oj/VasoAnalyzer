"""Application bootstrap utilities for the VasoAnalyzer desktop app."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import QCoreApplication, Qt, QTimer
from PyQt5.QtGui import QFont, QIcon, QPalette, QColor, QPainter, QPainterPath, QPixmap
from PyQt5.QtWidgets import QApplication, QSplashScreen

from vasoanalyzer.ui.main_window import VasoAnalyzerApp
from vasoanalyzer.ui.theme import apply_light_theme
from utils.config import APP_VERSION

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

    def __init__(self, project_path: Optional[str] = None) -> None:
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
        apply_light_theme()
        self.app.setStyle("Fusion")

        palette = QPalette()
        palette.setColor(QPalette.Window, QColor("#f5f5f5"))
        palette.setColor(QPalette.Base, QColor("#ffffff"))
        palette.setColor(QPalette.AlternateBase, QColor("#f7f7f7"))
        palette.setColor(QPalette.ToolTipBase, QColor("#ffffff"))
        palette.setColor(QPalette.Button, QColor("#e0e0e0"))
        palette.setColor(QPalette.ButtonText, QColor("#222222"))
        self.app.setPalette(palette)

        if resource_path is not None:
            try:
                style_path = Path(resource_path("style.qss"))
            except TypeError:  # pragma: no cover - resource helper missing
                style_path = None
            if style_path and style_path.exists():
                with style_path.open() as fh:
                    self.app.setStyleSheet(self.app.styleSheet() + fh.read())

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
        if hasattr(self, "splash"):
            self.splash.close()

        try:
            window = VasoAnalyzerApp()
            window.show()
            if self.project_path:
                QTimer.singleShot(100, lambda: window.open_recent_project(self.project_path))
            else:
                QTimer.singleShot(100, window.show_welcome_dialog)
            self.window = window
            log.info("Main window started successfully")
        except Exception as exc:  # pragma: no cover - defensive logging for GUI
            log.exception("Error launching main window")

    # ------------------------------------------------------------------
    def run(self) -> None:
        sys.exit(self.app.exec_())


__all__ = ["VasoAnalyzerLauncher"]
