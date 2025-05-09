# ===== Main Launcher =====
import sys
import os
import base64
from PyQt5.QtWidgets import QApplication, QSplashScreen
from PyQt5.QtGui import QPixmap
from PyQt5.QtCore import Qt, QTimer
import re
from PyQt5.QtWidgets import QFileDialog, QMessageBox
from PyQt5.QtGui import QIcon

from vasoanalyzer.gui import VasoAnalyzerApp
import matplotlib
import matplotlib.pyplot as plt
from matplotlib import rcParams
from matplotlib.backends.backend_qt5 import MainWindow

# ===== Embedded Splash Image =====
# Resolve base64 splash path for source vs. PyInstaller bundle
if hasattr(sys, "_MEIPASS"):
	base_path = os.path.join(sys._MEIPASS, "vasoanalyzer")
else:
	base_path = os.path.join(os.path.dirname(__file__), "vasoanalyzer")

splash_file = os.path.join(base_path, "splash_image_base64.txt")

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

		# === Load and Show Splash Screen from Embedded Data ===
		try:
			with open(splash_file, 'r') as f:
				splash_base64 = f.read().strip()
			splash_data = base64.b64decode(splash_base64)
			splash_pix = QPixmap()
			splash_pix.loadFromData(splash_data)

			if splash_pix.isNull():
				print("⚠️ Splash image could not be loaded from embedded data.")
				self.start_main_app()
			else:
				splash_pix = splash_pix.scaled(400, 400, Qt.KeepAspectRatio, Qt.SmoothTransformation)
				self.splash = QSplashScreen(splash_pix, Qt.WindowStaysOnTopHint)
				self.splash.setMask(splash_pix.mask())
				self.splash.show()

				QTimer.singleShot(2500, self.start_main_app)
		except Exception as e:
			print(f"⚠️ Error loading splash image: {e}")
			self.start_main_app()

	def start_main_app(self):
		if hasattr(self, 'splash'):
			self.splash.close()
		try:
			print("🚀 Attempting to create VasoAnalyzerApp window...")
			self.window = VasoAnalyzerApp()
			self.window.show()
			print("✅ Main window shown successfully!")
		except Exception as e:
			print(f"❗ Error launching main window: {e}")

	def run(self):
		sys.exit(self.app.exec_())

if __name__ == "__main__":
	launcher = VasoAnalyzerLauncher()
	launcher.run()