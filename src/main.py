# ===== Main Launcher =====
import sys
import os
import base64
import h5py
import pickle
import numpy as np
from datetime import datetime
from PyQt5.QtWidgets import QApplication, QSplashScreen, QAction
from PyQt5.QtGui import QPixmap
from PyQt5.QtCore import Qt, QTimer
import re
from PyQt5.QtWidgets import QFileDialog, QMessageBox
from PyQt5.QtGui import QIcon
from utils.config import APP_VERSION

from vasoanalyzer.gui import VasoAnalyzerApp
import matplotlib
import matplotlib.pyplot as plt
from matplotlib import rcParams
from matplotlib.backends.backend_qt5 import MainWindow

# ===== Helper to fix Matplotlib dialogs =====
def fix_matplotlib_dialogs():
	for fig_num in plt.get_fignums():
		fig = plt.figure(fig_num)
		window = fig.canvas.manager.window
		if isinstance(window, MainWindow):
			window.setStyleSheet("""
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
			""")

class VasoAnalyzerLauncher:
	def __init__(self):
		self.app = QApplication(sys.argv)

		# ===== Platform-specific icon =====
		if sys.platform.startswith("win"):
			icon_path = os.path.join(os.path.dirname(__file__), 'vasoanalyzer', 'VasoAnalyzerIcon.ico')
		elif sys.platform == "darwin":
			icon_path = os.path.join(os.path.dirname(__file__), 'vasoanalyzer', 'VasoAnalyzerIcon.icns')
		else:
			icon_path = None

		if icon_path and os.path.exists(icon_path):
			self.app.setWindowIcon(QIcon(icon_path))

		# === Global Qt Stylesheet Patch ===
		self.app.setStyleSheet("""
			* {
				color: black;
				background-color: white;
			}
			QPushButton {
				background-color: #FFFFFF;
				border: 1px solid #CCCCCC;
				border-radius: 8px;
				padding: 6px 12px;
			}
			QLabel {
				color: black;
			}
			QLineEdit, QComboBox, QTextEdit {
				background-color: #F5F5F5;
				border: 1px solid #AAAAAA;
				padding: 4px;
				border-radius: 4px;
			}
			QCheckBox, QRadioButton {
				color: black;
			}
			QDialog {
				background-color: #FFFFFF;
				color: black;
			}
		""")

		# === Matplotlib rcParams Patch for Plot Styling ===
		rcParams.update({
			'axes.labelcolor': 'black',
			'xtick.color': 'black',
			'ytick.color': 'black',
			'text.color': 'black',
			'axes.facecolor': 'white',
			'figure.facecolor': 'white',
			'savefig.facecolor': 'white',
			'figure.edgecolor': 'white',
			'savefig.edgecolor': 'white',
		})

		# === Load and Show Splash Screen from PNG file ===
		splash_path = os.path.join(os.path.dirname(__file__), "vasoanalyzer", "VasoAnalyzerSplashScreen.png")
		splash_pix = QPixmap(splash_path)
		
		if splash_pix.isNull():
			print("⚠️ Splash image could not be loaded from:", splash_path)
			self.start_main_app()
		else:
			self.splash = QSplashScreen(splash_pix, Qt.WindowStaysOnTopHint)
			self.splash.setMask(splash_pix.mask())
			self.splash.show()
		
			QTimer.singleShot(2500, self.start_main_app)

	def start_main_app(self):
		if hasattr(self, 'splash'):
			self.splash.close()
		try:
			print("🚀 Attempting to create VasoAnalyzerApp window...")
			self.window = VasoAnalyzerApp()
			file_menu = self.window.menuBar().actions()[0].menu()
			save_act = QAction("Save Project", self.window)
			save_act.triggered.connect(self.window.save_project)
			open_act = QAction("Open Project", self.window)
			open_act.triggered.connect(self.window.open_project)
			file_menu.addAction(save_act)
			file_menu.addAction(open_act)
			self.window.show()
			print("✅ Main window shown successfully!")
		except Exception as e:
			print(f"❗ Error launching main window: {e}")

	def run(self):
		sys.exit(self.app.exec_())

if __name__ == "__main__":
	launcher = VasoAnalyzerLauncher()
	launcher.run()