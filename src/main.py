# ===== Main Launcher =====
import sys
import os
import logging
import base64
import pickle
import numpy as np
from datetime import datetime
from PyQt5.QtWidgets import QApplication, QSplashScreen, QAction
from PyQt5.QtGui import QPixmap
from PyQt5.QtCore import Qt, QTimer, QCoreApplication
import re
from PyQt5.QtWidgets import QFileDialog, QMessageBox
from PyQt5.QtGui import QIcon
from utils.config import APP_VERSION

from vasoanalyzer.ui.main_window import VasoAnalyzerApp
from vasoanalyzer.theme_manager import apply_light_theme
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5 import MainWindow

log = logging.getLogger(__name__)


# ===== Helper to fix Matplotlib dialogs =====
def fix_matplotlib_dialogs():
    for fig_num in plt.get_fignums():
        fig = plt.figure(fig_num)
        window = fig.canvas.manager.window
        if isinstance(window, MainWindow):
            window.setStyleSheet(
                """
                QWidget {
                    background-color: #FFFFFF;
                    color: black;
                }
                QLineEdit, QComboBox, QTextEdit {
                    background-color: #F5F5F5;
                    color: black;
                }
                QPushButton {
                    background-color: #FFFFFF;
                    color: black;
                    border: 1px solid #CCCCCC;
                    border-radius: 6px;
                    padding: 4px;
                }
                QDialogButtonBox QPushButton {
                    background-color: #FFFFFF;
                    color: black;
                }
            """
            )


class VasoAnalyzerLauncher:
    def __init__(self):
        # Enable HiDPI scaling and crisp pixmaps on all displays
        QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

        self.app = QApplication(sys.argv)

        # ===== Platform-specific icon =====
        if sys.platform.startswith("win"):
            icon_path = os.path.join(
                os.path.dirname(__file__), "vasoanalyzer", "VasoAnalyzerIcon.ico"
            )
        elif sys.platform == "darwin":
            icon_path = os.path.join(
                os.path.dirname(__file__), "vasoanalyzer", "VasoAnalyzerIcon.icns"
            )
        else:
            icon_path = None

        if icon_path and os.path.exists(icon_path):
            self.app.setWindowIcon(QIcon(icon_path))

        # === Apply the application theme ===
        apply_light_theme()

        # === Load and Show Splash Screen from PNG file ===
        splash_path = os.path.join(
            os.path.dirname(__file__), "vasoanalyzer", "VasoAnalyzerSplashScreen.png"
        )
        splash_pix = QPixmap(splash_path)

        if splash_pix.isNull():
            print("⚠️ Splash image could not be loaded from:", splash_path)
            self.start_main_app()
        else:
            device_ratio = self.app.devicePixelRatio()
            target_size = int(400 * device_ratio)
            splash_pix = splash_pix.scaled(
                target_size,
                target_size,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            splash_pix.setDevicePixelRatio(device_ratio)
            self.splash = QSplashScreen(splash_pix, Qt.WindowStaysOnTopHint)
            self.splash.setMask(splash_pix.mask())
            self.splash.show()

            QTimer.singleShot(2500, self.start_main_app)

    def start_main_app(self):
        if hasattr(self, "splash"):
            self.splash.close()
        try:
            print("🚀 Attempting to create VasoAnalyzerApp window...")
            self.window = VasoAnalyzerApp()
            self.window.show()
            QTimer.singleShot(100, self.window.show_welcome_dialog)
            print("✅ Main window shown successfully!")
        except Exception as e:
            print(f"❗ Error launching main window: {e}")

    def run(self):
        sys.exit(self.app.exec_())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    launcher = VasoAnalyzerLauncher()
    launcher.run()
