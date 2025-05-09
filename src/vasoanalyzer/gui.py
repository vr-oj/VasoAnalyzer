# [A] ========================= IMPORTS AND GLOBAL CONFIG ============================
import sys, os, pickle
import numpy as np
import pandas as pd
import tifffile
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
from matplotlib import rcParams
rcParams.update({
'axes.labelcolor': 'black',
'xtick.color': 'black',
'ytick.color': 'black',
'text.color': 'black',
'figure.facecolor': 'white',
'figure.edgecolor': 'white',
'savefig.facecolor': 'white',
'savefig.edgecolor': 'white',
})

from PyQt5.QtWidgets import (
	QMainWindow, QWidget, QPushButton, QFileDialog, QVBoxLayout, QHBoxLayout,
	QSlider, QLabel, QTableWidget, QTableWidgetItem, QAbstractItemView,
	QHeaderView, QMessageBox, QInputDialog, QMenu, QSizePolicy, QAction,
	QToolBar, QToolButton, QSpacerItem
)

from PyQt5.QtGui import QPixmap, QImage, QIcon
from PyQt5.QtCore import Qt, QTimer, QSize

from vasoanalyzer.trace_loader import load_trace
from vasoanalyzer.tiff_loader import load_tiff
from vasoanalyzer.event_loader import load_events
from .excel_mapper import ExcelMappingDialog
from vasoanalyzer.excel_mapper import update_excel_file

# [B] ========================= MAIN CLASS DEFINITION ================================
class VasoAnalyzerApp(QMainWindow):
	def __init__(self):
		super().__init__()
		icon_path = os.path.join(os.path.dirname(__file__), 'VasoAnalyzerIcon.icns')
		self.setWindowIcon(QIcon(icon_path))

		self.setStyleSheet("""
			QPushButton {
				color: black;
			}
		""")

		# ===== Setup App Window =====
		self.setWindowTitle("VasoAnalyzer 2.5 - Python Edition")
		self.setGeometry(100, 100, 1280, 720)

		# ===== Initialize State =====
		self.trace_data = None
		self.trace_file_path = None
		self.snapshot_frames = []
		self.current_frame = 0
		self.event_labels = []
		self.event_times = []
		self.event_text_objects = []
		self.event_table_data = []
		self.selected_event_marker = None
		self.pinned_points = []
		self.slider_marker = None
		self.recording_interval = 1 #0.14	# 140 ms per frame
		self.last_replaced_event = None
		self.excel_auto_path = None		# Path to Excel file for auto-update
		self.excel_auto_column = None	# Column letter to use for auto-update

		# ===== Axis + Slider State =====
		self.axis_dragging = False
		self.axis_drag_start = None
		self.drag_direction = None
		self.scroll_slider = None
		self.window_width = None

		# ===== Build UI =====
		self.initUI()

	def icon_path(self, filename):
		return os.path.join(os.path.dirname(__file__), '..', 'icons', filename)


# [C] ========================= UI SETUP (initUI) ======================================
	def initUI(self):
		self.setStyleSheet("""
			QWidget { background-color: #F5F5F5; font-family: 'Arial'; font-size: 13px; }
			QPushButton { background-color: #FFFFFF; border: 1px solid #CCCCCC; border-radius: 6px; padding: 6px 12px; }
			QPushButton:hover { background-color: #E6F0FF; }
			QToolButton { background-color: #FFFFFF; border: 1px solid #CCCCCC; border-radius: 6px; padding: 6px; margin: 2px; }
			QToolButton:hover { background-color: #D6E9FF; }
			QToolButton:checked { background-color: #CCE5FF; border: 1px solid #3399FF; }
			QHeaderView::section { background-color: #E0E0E0; font-weight: bold; padding: 6px; }
			QTableWidget { gridline-color: #DDDDDD; }
			QTableWidget::item { padding: 6px; }
		""")
		central_widget = QWidget()
		self.setCentralWidget(central_widget)
		main_layout = QVBoxLayout(central_widget)
		main_layout.setContentsMargins(0, 0, 0, 0)
		main_layout.setSpacing(0)
		self.fig = Figure(figsize=(8, 4), facecolor='white')
		self.canvas = FigureCanvas(self.fig)
		self.ax = self.fig.add_subplot(111)
		self.grid_visible = True  # Track grid visibility
		
		# ===== Initialize Matplotlib Toolbar =====
		self.toolbar = NavigationToolbar(self.canvas, self)
		self.toolbar.setIconSize(QSize(24, 24))
		self.toolbar.setStyleSheet("""
			QToolBar {
				background-color: #F0F0F0;
				padding: 2px;
				border: none;
			}
		""")
		self.toolbar.setContentsMargins(0, 0, 0, 0)
		
		# Remove stray/empty buttons
		if hasattr(self.toolbar, 'coordinates'):
			self.toolbar.coordinates = lambda *args, **kwargs: None
			for act in self.toolbar.actions():
				if isinstance(act, QAction) and act.text() == "":
					self.toolbar.removeAction(act)
		
		visible_buttons = [a for a in self.toolbar.actions() if not a.icon().isNull()]
		if len(visible_buttons) >= 8:
			visible_buttons[0].setToolTip("Home: Reset zoom and pan")
			visible_buttons[1].setToolTip("Back: Previous view")
			visible_buttons[2].setToolTip("Forward: Next view")
			visible_buttons[3].setToolTip("Pan: Click and drag plot")
			visible_buttons[4].setToolTip("Zoom: Draw box to zoom in")
		
			# [5] Subplot layout (borders + spacings)
			layout_btn = visible_buttons[5]
			layout_btn.setToolTip("Configure subplot layout")
			layout_btn.triggered.disconnect()
			layout_btn.triggered.connect(self.toolbar.configure_subplots)
		
			# [6] Axes and title editor
			axes_btn = visible_buttons[6]
			axes_btn.setToolTip("Edit axis ranges and titles")
			axes_btn.triggered.disconnect()
			axes_btn.triggered.connect(self.toolbar.edit_parameters)
		
			# [Inject] Aa: Plot style editor
			style_btn = QToolButton()
			style_btn.setText("Aa")
			style_btn.setToolTip("Customize plot fonts and layout")
			style_btn.setStyleSheet("""
				QToolButton {
					background-color: #FFFFFF;
					border: 1px solid #CCCCCC;
					border-radius: 6px;
					padding: 6px;
					margin: 2px;
					font-weight: bold;
					font-size: 14px;
				}
				QToolButton:hover {
					background-color: #E0F0FF;
				}
			""")
			style_btn.clicked.connect(self.open_plot_style_editor)
			self.toolbar.insertWidget(visible_buttons[7], style_btn)
		
			# [Inject] Grid toggle button
			grid_btn = QToolButton()
			grid_btn.setText("Grid")
			grid_btn.setToolTip("Toggle grid visibility")
			grid_btn.setCheckable(True)
			grid_btn.setChecked(self.grid_visible)
			grid_btn.clicked.connect(self.toggle_grid)
			self.toolbar.insertWidget(visible_buttons[7], grid_btn)
		
			# [7] Save/export button
			save_btn = visible_buttons[7]
			save_btn.setToolTip("Save As… Export high-res plot")
			save_btn.triggered.disconnect()
			save_btn.triggered.connect(self.export_high_res_plot)



	
		# ===== Unified Top Row: Toolbar + Load Buttons =====
		top_row_layout = QHBoxLayout()
		top_row_layout.setContentsMargins(6, 4, 6, 2)
		top_row_layout.setSpacing(8)
	
		top_row_layout.addWidget(self.toolbar)
	
		self.loadTraceBtn = QPushButton("📂 Load Trace + Events")
		self.loadTraceBtn.setToolTip("Load .csv trace file and auto-load matching event table")
		self.loadTraceBtn.clicked.connect(self.load_trace_and_events)
	
		self.load_snapshot_button = QPushButton("🖼️ Load _Result.tiff")
		self.load_snapshot_button.setToolTip("Load Vasotracker _Result.tiff snapshot")
		self.load_snapshot_button.clicked.connect(self.load_snapshot)
	
		self.excel_btn = QPushButton("📊 Excel")
		self.excel_btn.setToolTip("Map Events to Excel Template")
		self.excel_btn.setEnabled(False)
		self.excel_btn.clicked.connect(self.open_excel_mapping_dialog)
	
		self.trace_file_label = QLabel("No trace loaded")
		self.trace_file_label.setStyleSheet("color: gray; font-size: 12px; padding-left: 10px;")
		self.trace_file_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
	
		top_row_layout.addWidget(self.loadTraceBtn)
		top_row_layout.addWidget(self.load_snapshot_button)
		top_row_layout.addWidget(self.excel_btn)
		top_row_layout.addWidget(self.trace_file_label)
	
		main_layout.addLayout(top_row_layout)
	
		# ===== Plot and Scroll Slider =====
		self.scroll_slider = QSlider(Qt.Horizontal)
		self.scroll_slider.setMinimum(0)
		self.scroll_slider.setMaximum(1000)
		self.scroll_slider.setSingleStep(1)
		self.scroll_slider.setValue(0)
		self.scroll_slider.valueChanged.connect(self.scroll_plot)
		self.scroll_slider.hide()
		self.scroll_slider.setToolTip("Scroll timeline (X-axis)")
	
		plot_layout = QVBoxLayout()
		plot_layout.setContentsMargins(6, 0, 6, 6)
		plot_layout.setSpacing(4)
		plot_layout.addWidget(self.canvas)
		plot_layout.addWidget(self.scroll_slider)
	
		left_layout = QVBoxLayout()
		left_layout.setSpacing(0)
		left_layout.setContentsMargins(0, 0, 0, 0)
		left_layout.addLayout(plot_layout)
	
		# ===== Snapshot Viewer and Table =====
		self.snapshot_label = QLabel("Snapshot will appear here")
		self.snapshot_label.setAlignment(Qt.AlignCenter)
		self.snapshot_label.setFixedSize(400, 300)
		self.snapshot_label.setStyleSheet("background-color: white; border: 1px solid #999;")
		self.snapshot_label.hide()
	
		self.slider = QSlider(Qt.Horizontal)
		self.slider.setMinimum(0)
		self.slider.setValue(0)
		self.slider.valueChanged.connect(self.change_frame)
		self.slider.hide()
		self.slider.setToolTip("Navigate TIFF frames")
	
		self.event_table = QTableWidget()
		self.event_table.setColumnCount(4)
		self.event_table.setHorizontalHeaderLabels(["Event", "Time (s)", "Frame", "ID (µm)"])
		self.event_table.setMinimumWidth(400)
		self.event_table.setEditTriggers(QAbstractItemView.DoubleClicked)
		self.event_table.setSelectionBehavior(QAbstractItemView.SelectRows)
		self.event_table.setStyleSheet("background-color: white; color: black;")
		self.event_table.horizontalHeader().setStretchLastSection(True)
		self.event_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
		self.event_table.cellClicked.connect(self.table_row_clicked)
		self.event_table.itemChanged.connect(self.handle_table_edit)
	
		snapshot_layout = QVBoxLayout()
		snapshot_layout.setSpacing(4)
		snapshot_layout.setContentsMargins(0, 0, 0, 0)
		snapshot_layout.addWidget(self.snapshot_label)
		snapshot_layout.addWidget(self.slider)
	
		right_layout = QVBoxLayout()
		right_layout.setSpacing(6)
		right_layout.setContentsMargins(0, 0, 0, 0)
		right_layout.addLayout(snapshot_layout)
		right_layout.addWidget(self.event_table)
	
		# ===== Top-Level Layout (Left + Right) =====
		top_layout = QHBoxLayout()
		top_layout.setContentsMargins(0, 0, 0, 0)
		top_layout.setSpacing(0)
		top_layout.addLayout(left_layout, 4)
		top_layout.addLayout(right_layout, 1)
	
		main_layout.addLayout(top_layout)
	
		# ===== Hover Label =====
		self.hover_label = QLabel("", self)
		self.hover_label.setStyleSheet("""
			background-color: rgba(255, 255, 255, 220);
			border: 1px solid #888;
			border-radius: 5px;
			padding: 2px 6px;
			font-size: 12px;
		""")
		self.hover_label.hide()
	
		# ===== Canvas Interactions =====
		self.canvas.mpl_connect("draw_event", self.update_event_label_positions)
		self.canvas.mpl_connect("motion_notify_event", self.update_event_label_positions)
		self.canvas.mpl_connect("motion_notify_event", self.update_hover_label)
		self.canvas.mpl_connect("button_press_event", self.handle_click_on_plot)
		self.canvas.mpl_connect("button_release_event", lambda event: QTimer.singleShot(100, lambda: self.on_mouse_release(event)))

		# Add context menu to snapshot label
		self.snapshot_label.setContextMenuPolicy(Qt.CustomContextMenu)
		self.snapshot_label.customContextMenuRequested.connect(self.show_snapshot_context_menu)

	def show_snapshot_context_menu(self, pos):
		if not hasattr(self, 'snapshot_frames') or not self.snapshot_frames:
			return
			
		menu = QMenu(self)
		view_metadata_action = menu.addAction("📋 View Frame Metadata")
		view_metadata_action.triggered.connect(self.show_current_frame_metadata)
		
		menu.exec_(self.snapshot_label.mapToGlobal(pos))

# [D] ========================= FILE LOADERS: TRACE / EVENTS / TIFF =====================
	def load_trace_and_events(self):
		file_path, _ = QFileDialog.getOpenFileName(self, "Select Trace File", "", "CSV Files (*.csv)")
		if not file_path:
			return
	
		try:
			# Load trace
			self.trace_data = load_trace(file_path)
			self.trace_file_path = os.path.dirname(file_path)
			trace_filename = os.path.basename(file_path)
			self.trace_file_label.setText(f"🧪 {trace_filename}")
			self.update_plot()
		except Exception as e:
			QMessageBox.critical(self, "Trace Load Error", f"Failed to load trace file:\n{e}")
			return
	
		# Try to load matching _table.csv file
		base_name = os.path.splitext(trace_filename)[0]
		event_filename = f"{base_name}_table.csv"
		event_path = os.path.join(self.trace_file_path, event_filename)
	
		if os.path.exists(event_path):
			try:
				self.event_labels, self.event_times, self.event_frames = load_events(event_path)
	
				# Generate table data by sampling diameters
				diam_trace = self.trace_data['Inner Diameter']
				time_trace = self.trace_data['Time (s)']
				self.event_table_data = []
	
				for i in range(len(self.event_times)):
					if i < len(self.event_times) - 1:
						t_sample = self.event_times[i+1] - 2  # 2 sec before next
						idx_pre = np.argmin(np.abs(time_trace - t_sample))
					else:
						idx_pre = -1

					# Calculate frame number based on event time and recording interval
					frame_number = self.event_times[i]

					diam_pre = diam_trace.iloc[idx_pre]
					self.event_table_data.append((
						self.event_labels[i],
						round(self.event_times[i], 2),
						frame_number,  # Using actual frame number
						round(diam_pre, 2)
					))
	
				self.populate_table()
				self.update_plot()
				self.excel_btn.setEnabled(True)
			except Exception as e:
				QMessageBox.warning(self, "Event Load Error", f"Trace loaded, but failed to load events:\n{e}")
		else:
			QMessageBox.information(self, "Event File Not Found", f"No matching event file found:\n{event_filename}")

	def load_snapshot(self):
		file_path, _ = QFileDialog.getOpenFileName(self, "Open Result TIFF", "", "TIFF Files (*.tif *.tiff)")
		if file_path:
			try:
				frames, frames_metadata = load_tiff(file_path)
				valid_frames = []
				valid_metadata = []
				
				# Filter out empty/corrupt frames
				for i, frame in enumerate(frames):
					if frame is not None and frame.size > 0:
						valid_frames.append(frame)
						if i < len(frames_metadata):
							valid_metadata.append(frames_metadata[i])
						else:
							valid_metadata.append({})

				if len(valid_frames) < len(frames):
					QMessageBox.warning(self, "TIFF Warning", "Some TIFF frames were empty or corrupted and were skipped.")

				self.snapshot_frames = valid_frames
				self.frames_metadata = valid_metadata
				
				if self.snapshot_frames:
					self.display_frame(0)
					self.slider.setMaximum(len(self.snapshot_frames) - 1)
					self.slider.setValue(0)
					self.snapshot_label.show()
					self.slider.show()
					self.slider_marker = None
					
					# Create metadata button if it doesn't exist
					if not hasattr(self, 'metadata_btn'):
						self.metadata_btn = QPushButton("📋 View Metadata")
						self.metadata_btn.clicked.connect(self.show_current_frame_metadata)
						
						# Find the layout containing the snapshot label
						right_layout = self.snapshot_label.parent().layout()
						right_layout.addWidget(self.metadata_btn)
					else:
						self.metadata_btn.show()
				
			except Exception as e:
				QMessageBox.critical(self, "Error", f"Failed to load TIFF file:\n{e}")

	def show_current_frame_metadata(self):
		"""Show metadata for the currently displayed frame"""
		if not hasattr(self, 'frames_metadata') or not self.frames_metadata:
			QMessageBox.information(self, "Metadata", "No metadata available for this TIFF file.")
			return
		
		current_idx = self.slider.value()
		if current_idx >= len(self.frames_metadata):
			QMessageBox.information(self, "Metadata", "No metadata available for this frame.")
			return
		
		# Get metadata for current frame
		metadata = self.frames_metadata[current_idx]
		
		# Format metadata as text
		metadata_text = f"Frame {current_idx} Metadata:\n" + "-" * 40 + "\n"
		
		# Sort keys alphabetically for consistent display
		for key in sorted(metadata.keys()):
			value = metadata[key]
			# Handle arrays specially to avoid overwhelming the display
			if isinstance(value, (list, tuple, np.ndarray)) and len(str(value)) > 100:
				metadata_text += f"{key}: [Array with shape {np.array(value).shape}]\n"
			else:
				metadata_text += f"{key}: {value}\n"
		
		# Show dialog with metadata
		msg = QMessageBox(self)
		msg.setWindowTitle(f"Frame {current_idx} Metadata")
		msg.setText(metadata_text)
		msg.setDetailedText(str(metadata))  # Full metadata in detailed view
		msg.setStandardButtons(QMessageBox.Ok)
		msg.setIcon(QMessageBox.Information)
		
		# Make the dialog bigger
		msg.setStyleSheet("QLabel{min-width: 500px; min-height: 400px;}")
		
		msg.exec_()

	def display_frame(self, index):
		if not self.snapshot_frames:
			return

		# Clamp index to valid range
		if index < 0 or index >= len(self.snapshot_frames):
			print(f"⚠️ Frame index {index} out of bounds.")
			return

		frame = self.snapshot_frames[index]

		# Skip if frame is empty or corrupted
		if frame is None or frame.size == 0:
			print(f"⚠️ Skipping empty or corrupted frame at index {index}")
			return

		try:
			if frame.ndim == 2:
				height, width = frame.shape
				q_img = QImage(frame.data, width, height, QImage.Format_Grayscale8)
			elif frame.ndim == 3:
				height, width, channels = frame.shape
				if channels == 3:
					q_img = QImage(frame.data, width, height, 3 * width, QImage.Format_RGB888)
				else:
					raise ValueError(f"Unsupported TIFF frame format: {frame.shape}")
			else:
				raise ValueError(f"Unknown TIFF frame dimensions: {frame.shape}")

			self.snapshot_label.setPixmap(QPixmap.fromImage(q_img).scaled(
				self.snapshot_label.width(), self.snapshot_label.height(), Qt.KeepAspectRatio))
		except Exception as e:
			print(f"⚠️ Error displaying frame {index}: {e}")

	def change_frame(self):
		if not self.snapshot_frames:
			return

		idx = self.slider.value()
		self.current_frame = idx
		self.display_frame(idx)
		self.update_slider_marker()

		# Add a small indicator that shows metadata is available
		if hasattr(self, 'metadata_btn') and idx < len(self.frames_metadata):
			num_tags = len(self.frames_metadata[idx])
			self.metadata_btn.setText(f"📋 View Metadata ({num_tags} tags)")

	def update_slider_marker(self):
		if self.trace_data is None or not self.snapshot_frames:
			return

		current_frame_idx = self.slider.value()
		
		# Get the actual frame number from metadata if available
		if hasattr(self, 'frames_metadata') and current_frame_idx < len(self.frames_metadata):
			frame_meta = self.frames_metadata[current_frame_idx]
			
			if 'FrameNumber' in frame_meta:
				# Use the actual frame number from metadata
				frame_number = frame_meta['FrameNumber']
				# Convert frame number to time using recording interval
				t_current = frame_number
				print(f"Using FrameNumber {frame_number} → time: {t_current:.2f}s")
			else:
				# Fall back to slider index if frame number isn't available
				t_current = current_frame_idx
				print(f"No FrameNumber in metadata, using slider index: {t_current:.2f}s")
		else:
			# Fall back to slider index if no metadata is available
			t_current = current_frame_idx
			print(f"No metadata available, using slider index: {t_current:.2f}s")

		if self.slider_marker is None:
			self.slider_marker = self.ax.axvline(x=t_current, color='red', linestyle='--', linewidth=1.5, label="TIFF Frame")
		else:
			self.slider_marker.set_xdata([t_current, t_current])

		self.canvas.draw_idle()
		self.canvas.flush_events()

	def populate_event_table_from_df(self, df):
		self.event_table.setRowCount(len(df))
		for row in range(len(df)):
			self.event_table.setItem(row, 0, QTableWidgetItem(str(df.iloc[row].get("EventLabel", ""))))
			self.event_table.setItem(row, 1, QTableWidgetItem(str(df.iloc[row].get("Time (s)", ""))))
			self.event_table.setItem(row, 2, QTableWidgetItem(str(df.iloc[row].get("ID (µm)", ""))))


	def update_event_label_positions(self, event=None):
		if not hasattr(self, 'event_text_objects') or not self.event_text_objects:
			return

		y_min, y_max = self.ax.get_ylim()
		y_top = min(y_max - 5, y_max * 0.95)

		for txt, x in self.event_text_objects:
			txt.set_position((x, y_top))

# [E] ========================= PLOTTING AND EVENT SYNC ============================
	def update_plot(self):
		if self.trace_data is None:
			return

		self.ax.clear()
		self.ax.set_facecolor("white")
		self.ax.tick_params(colors='black')
		self.ax.xaxis.label.set_color('black')
		self.ax.yaxis.label.set_color('black')
		self.ax.title.set_color('black')
		self.event_text_objects = []

		# Plot trace
		t = self.trace_data['Time (s)']
		d = self.trace_data['Inner Diameter']
		self.ax.plot(t, d, 'k-', linewidth=1.5)
		self.ax.set_xlabel("Time (s or frames)")
		self.ax.set_ylabel("Inner Diameter (µm)")
		self.ax.grid(True, color='#CCC')

		# Plot events if available
		if self.event_labels and self.event_times:
			self.event_table_data = []
			offset_sec = 2
			nEv = len(self.event_times)
			diam_trace = self.trace_data['Inner Diameter']
			time_trace = self.trace_data['Time (s)']

			for i in range(nEv):
				idx_ev = np.argmin(np.abs(time_trace - self.event_times[i]))
				diam_at_ev = diam_trace.iloc[idx_ev]

				if i < nEv - 1:
					t_sample = self.event_times[i+1] - offset_sec
					idx_pre = np.argmin(np.abs(time_trace - t_sample))
				else:
					idx_pre = -1
				diam_pre = diam_trace.iloc[idx_pre]

				frame_number = self.event_frames[i]

				# Vertical line
				self.ax.axvline(x=frame_number, color='black', linestyle='--', linewidth=0.8)

				# Label on plot
				txt = self.ax.text(
					frame_number, 0, self.event_labels[i],
					rotation=90,
					verticalalignment='top',
					horizontalalignment='right',
					fontsize=8,
					color='black',
					clip_on=True
				)
				self.event_text_objects.append((txt, frame_number))

				# Table entry
				self.event_table_data.append((
					self.event_labels[i],
					round(self.event_times[i], 2),
					frame_number,
					round(diam_pre, 2)
				))

			self.populate_table()
			self.auto_export_table()

		self.canvas.draw_idle()

	def scroll_plot(self):
		if self.trace_data is None:
			return

		full_t_min = self.trace_data['Time (s)'].min()
		full_t_max = self.trace_data['Time (s)'].max()
		xlim = self.ax.get_xlim()
		window_width = xlim[1] - xlim[0]

		max_scroll = self.scroll_slider.maximum()
		slider_pos = self.scroll_slider.value()
		fraction = slider_pos / max_scroll

		new_left = full_t_min + (full_t_max - full_t_min - window_width) * fraction
		new_right = new_left + window_width

		self.ax.set_xlim(new_left, new_right)
		self.canvas.draw_idle()

# [F] ========================= EVENT TABLE MANAGEMENT ================================
	def populate_table(self):
		self.event_table.blockSignals(True)
		self.event_table.setRowCount(len(self.event_table_data))
		for row, (label, t, frame, d) in enumerate(self.event_table_data):
			self.event_table.setItem(row, 0, QTableWidgetItem(str(label)))
			self.event_table.setItem(row, 1, QTableWidgetItem(str(t)))
			self.event_table.setItem(row, 2, QTableWidgetItem(str(frame)))
			self.event_table.setItem(row, 3, QTableWidgetItem(str(d)))
		self.event_table.blockSignals(False)

	def handle_table_edit(self, item):
		row = item.row()
		col = item.column()

		# Only allow editing the third column (ID)
		if col != 3:
			self.populate_table()
			return

		try:
			new_val = float(item.text())
		except ValueError:
			QMessageBox.warning(self, "Invalid Input", "Please enter a valid number.")
			self.populate_table()
			return

		label = self.event_table_data[row][0]
		time = self.event_table_data[row][1]
		frame = self.event_table_data[row][2]  # Get the frame value
		old_val = self.event_table_data[row][3]  # Changed from index 2 to 3
		
		self.last_replaced_event = (row, old_val)
		self.event_table_data[row] = (label, time, frame, round(new_val, 2))  # Include frame in tuple

		self.auto_export_table()
		print(f"✏️ ID updated at {time:.2f}s → {new_val:.2f} µm")

	def table_row_clicked(self, row, col):
		if not self.event_table_data:
			return

		t = self.event_table_data[row][1]

		if self.selected_event_marker:
			self.selected_event_marker.remove()

		self.selected_event_marker = self.ax.axvline(x=t, color='blue', linestyle='--', linewidth=1.2)
		self.canvas.draw()
		
# [G] ========================= PIN INTERACTION LOGIC ================================
	def handle_click_on_plot(self, event):
		if event.inaxes != self.ax:
			return
	
		x = event.xdata
		if x is None:
			return
	
		# 🔴 Right-click = open pin context menu
		if event.button == 3:
			click_x, click_y = event.x, event.y
	
			for marker, label in self.pinned_points:
				data_x = marker.get_xdata()[0]
				data_y = marker.get_ydata()[0]
				pixel_x, pixel_y = self.ax.transData.transform((data_x, data_y))
				pixel_distance = np.hypot(pixel_x - click_x, pixel_y - click_y)
	
				if pixel_distance < 10:
					menu = QMenu(self)
					replace_action = menu.addAction("Replace Event Value…")
					delete_action = menu.addAction("Delete Pin")
					undo_action = menu.addAction("Undo Last Replacement")
					add_new_action = menu.addAction("➕ Add as New Event")
	
					action = menu.exec_(self.canvas.mapToGlobal(event.guiEvent.pos()))
					if action == delete_action:
						marker.remove()
						label.remove()
						self.pinned_points.remove((marker, label))
						self.canvas.draw_idle()
						return
					elif action == replace_action:
						self.handle_event_replacement(data_x, data_y)
						return
					elif action == undo_action:
						self.undo_last_replacement()
						return
					elif action == add_new_action:
						self.prompt_add_event(data_x, data_y)
						return
			return
	
		# 🟢 Left-click = add pin (unless toolbar zoom/pan is active)
		if event.button == 1 and not self.toolbar.mode:
			time_array = self.trace_data['Time (s)'].values
			id_array = self.trace_data['Inner Diameter'].values
			nearest_idx = np.argmin(np.abs(time_array - x))
			y = id_array[nearest_idx]
	
			marker = self.ax.plot(x, y, 'ro', markersize=6)[0]
			label = self.ax.annotate(
				f"{x:.2f} s\n{y:.1f} µm",
				xy=(x, y),
				xytext=(6, 6),
				textcoords='offset points',
				bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="gray", lw=1),
				fontsize=8
			)
	
			self.pinned_points.append((marker, label))
			self.canvas.draw_idle()
	
	def handle_event_replacement(self, x, y):
		if not self.event_labels or not self.event_times:
			print("No events available to replace.")
			return
	
		options = [f"{label} at {time:.2f}s" for label, time in zip(self.event_labels, self.event_times)]
		selected, ok = QInputDialog.getItem(
			self,
			"Select Event to Replace",
			"Choose the event whose value you want to replace:",
			options,
			0,
			False
		)
	
		if ok and selected:
			index = options.index(selected)
			event_label = self.event_labels[index]
			event_time = self.event_times[index]
	
			confirm = QMessageBox.question(
				self,
				"Confirm Replacement",
				f"Replace ID for '{event_label}' at {event_time:.2f}s with {y:.1f} µm?",
				QMessageBox.Yes | QMessageBox.No
			)
	
			if confirm == QMessageBox.Yes:
				old_value = self.event_table_data[index][2]
				self.last_replaced_event = (index, old_value)
				frame_num = self.event_table_data[index][2]
				self.event_table_data[index] = (event_label, round(event_time, 2), round(y, 2))
				self.populate_table()
				self.auto_export_table()
				print(f"✅ Replaced value at {event_time:.2f}s with {y:.1f} µm.")
	
	def prompt_add_event(self, x, y):
		if not self.event_table_data:
			QMessageBox.warning(self, "No Events", "You must load events before adding new ones.")
			return
	
		# Build label options and insertion points
		insert_labels = [f"{label} at {t:.2f}s" for label, t, _ in self.event_table_data]
		insert_labels.append("↘️ Add to end")  # final option
	
		selected, ok = QInputDialog.getItem(
			self,
			"Insert Event",
			"Insert new event before which existing event?",
			insert_labels,
			0,
			False
		)
	
		if not ok or not selected:
			return
	
		# Choose label for new event
		new_label, label_ok = QInputDialog.getText(
			self,
			"New Event Label",
			"Enter label for the new event:"
		)
	
		if not label_ok or not new_label.strip():
			return
	
		insert_idx = insert_labels.index(selected)

		# Calculate frame number based on time
		frame_number = int(x / self.recording_interval)

		new_entry = (new_label.strip(), round(x, 2), round(y, 2))
	
		# Insert into data
		if insert_idx == len(self.event_table_data):  # Add to end
			self.event_labels.append(new_label.strip())
			self.event_times.append(x)
			self.event_table_data.append(new_entry)
		else:
			self.event_labels.insert(insert_idx, new_label.strip())
			self.event_times.insert(insert_idx, x)
			self.event_table_data.insert(insert_idx, new_entry)
	
		self.populate_table()
		self.auto_export_table()
		print(f"➕ Inserted new event: {new_entry}")
	
	def undo_last_replacement(self):
		if self.last_replaced_event is None:
			QMessageBox.information(self, "Undo", "No replacement to undo.")
			return
	
		index, old_val = self.last_replaced_event
		label, time, frame, _ = self.event_table_data[index]
	
		self.event_table_data[index] = (label, time, frame, old_val)
		self.populate_table()
		self.auto_export_table()
	
		QMessageBox.information(self, "Undo", f"Restored value for '{label}' at {time:.2f}s.")
		self.last_replaced_event = None

# [H] ========================= HOVER LABEL AND CURSOR SYNC ===========================
	def update_hover_label(self, event):
		if event.inaxes != self.ax or self.trace_data is None:
			self.hover_label.hide()
			return
	
		x_val = event.xdata
		if x_val is None:
			self.hover_label.hide()
			return
	
		time_array = self.trace_data['Time (s)'].values
		id_array = self.trace_data['Inner Diameter'].values
		nearest_idx = np.argmin(np.abs(time_array - x_val))
		y_val = id_array[nearest_idx]
	
		frame_num = int(x_val)
		time_val = frame_num * self.recording_interval
		text = f"Frame: {frame_num}\nTime: {time_val:.2f} s\nID: {y_val:.2f} µm"

		self.hover_label.setText(text)
	
		cursor_offset_x = 10
		cursor_offset_y = -30
		self.hover_label.move(
			int(self.canvas.geometry().left() + event.guiEvent.pos().x() + cursor_offset_x),
			int(self.canvas.geometry().top() + event.guiEvent.pos().y() + cursor_offset_y)
		)
		self.hover_label.adjustSize()
		self.hover_label.show()

# [I] ========================= ZOOM + SLIDER LOGIC ================================
	def on_mouse_release(self, event):
		self.update_event_label_positions(event)

		# Deselect zoom after box zoom
		if self.toolbar.mode == 'zoom':
			self.toolbar.zoom()	 # toggles off
			self.toolbar.mode = ''
			self.toolbar._active = None
			self.canvas.setCursor(Qt.ArrowCursor)

		self.update_scroll_slider()

	def update_scroll_slider(self):
		if self.trace_data is None:
			return

		full_t_min = self.trace_data['Time (s)'].min()
		full_t_max = self.trace_data['Time (s)'].max()
		xlim = self.ax.get_xlim()
		self.window_width = xlim[1] - xlim[0]

		if self.window_width < (full_t_max - full_t_min):
			self.scroll_slider.show()
		else:
			self.scroll_slider.hide()

# [J] ========================= PLOT STYLE EDITOR ================================
	def open_plot_style_editor(self):
		from PyQt5.QtWidgets import QDialog
	
		dialog = PlotStyleDialog(self)
	
		# Store current styles to revert if Cancel is pressed
		prev_style = dialog.get_style()
	
		if dialog.exec_() == QDialog.Accepted:
			style = dialog.get_style()
			self.apply_plot_style(style)
		else:
			# Restore previous style (Cancel pressed)
			self.apply_plot_style(prev_style)
	
	def apply_plot_style(self, style):
		# Axis Titles
		self.ax.xaxis.label.set_fontsize(style['axis_font_size'])
		self.ax.xaxis.label.set_fontname(style['axis_font_family'])
		self.ax.xaxis.label.set_fontstyle('italic' if style['axis_italic'] else 'normal')
		self.ax.xaxis.label.set_fontweight('bold' if style['axis_bold'] else 'normal')
	
		self.ax.yaxis.label.set_fontsize(style['axis_font_size'])
		self.ax.yaxis.label.set_fontname(style['axis_font_family'])
		self.ax.yaxis.label.set_fontstyle('italic' if style['axis_italic'] else 'normal')
		self.ax.yaxis.label.set_fontweight('bold' if style['axis_bold'] else 'normal')
	
		# Tick Labels
		self.ax.tick_params(axis='x', labelsize=style['tick_font_size'])
		self.ax.tick_params(axis='y', labelsize=style['tick_font_size'])
	
		# Event Labels
		for txt, _ in self.event_text_objects:
			txt.set_fontsize(style['event_font_size'])
			txt.set_fontname(style['event_font_family'])
			txt.set_fontstyle('italic' if style['event_italic'] else 'normal')
			txt.set_fontweight('bold' if style['event_bold'] else 'normal')
	
		# Pinned Labels
		for marker, label in self.pinned_points:
			marker.set_markersize(style['pin_size'])
			label.set_fontsize(style['pin_font_size'])
			label.set_fontname(style['pin_font_family'])
			label.set_fontstyle('italic' if style['pin_italic'] else 'normal')
			label.set_fontweight('bold' if style['pin_bold'] else 'normal')
	
		# Line Width — ONLY change the main trace line
		main_line = self.ax.lines[0] if self.ax.lines else None
		if main_line:
			main_line.set_linewidth(style['line_width'])
	
		self.canvas.draw_idle()
		
	
	def open_customize_dialog(self):
		# Check visibility of any existing grid line
		is_grid_visible = any(line.get_visible() for line in self.ax.get_xgridlines())
		self.ax.grid(not is_grid_visible)
		self.toolbar.edit_parameters()
		self.canvas.draw_idle()


# [K] ========================= EXPORT LOGIC (CSV, FIG) ==============================
	def auto_export_table(self):
		if not self.trace_file_path:
			print("⚠️ No trace path set. Cannot export event table.")
			return

		try:
			output_dir = os.path.abspath(self.trace_file_path)
			csv_path = os.path.join(output_dir, "eventDiameters_output.csv")
			df = pd.DataFrame(self.event_table_data, columns=["Event", "Time (s)", "Frame", "ID (µm)"])
			df.to_csv(csv_path, index=False)
			print(f"✔ Event table auto-exported to:\n{csv_path}")
		except Exception as e:
			print(f"❌ Failed to auto-export event table:\n{e}")

		if self.excel_auto_path and self.excel_auto_column:
			update_excel_file(
				self.excel_auto_path,
				self.event_table_data,
				start_row=3,
				column_letter=self.excel_auto_column
			)

	def auto_export_editable_plot(self):
		if not self.trace_file_path:
			return
		try:
			pickle_path = os.path.join(os.path.abspath(self.trace_file_path), "tracePlot_output.fig.pickle")
			with open(pickle_path, 'wb') as f:
				pickle.dump(self.fig, f)
			print(f"✔ Editable trace figure saved to:\n{pickle_path}")
		except Exception as e:
			print(f"❌ Failed to save .pickle figure:\n{e}")

	def export_high_res_plot(self):
		if not self.trace_file_path:
			QMessageBox.warning(self, "Export Error", "No trace file loaded.")
			return

		save_path, _ = QFileDialog.getSaveFileName(
			self,
			"Save High-Resolution Plot",
			os.path.join(os.path.abspath(self.trace_file_path), "tracePlot_highres.tiff"),
			"TIFF Image (*.tiff);;SVG Vector (*.svg)"
		)

		if save_path:
			try:
				ext = os.path.splitext(save_path)[1].lower()
				if ext == ".svg":
					self.fig.savefig(save_path, format='svg', bbox_inches='tight')
				else:
					self.fig.savefig(save_path, format='tiff', dpi=600, bbox_inches='tight')

				QMessageBox.information(self, "Export Complete", f"Plot exported:\n{save_path}")
			except Exception as e:
				QMessageBox.critical(self, "Export Failed", str(e))


	def open_excel_mapping_dialog(self):
		if not self.event_table_data:
			QMessageBox.warning(self, "No Data", "No event data available to export.")
			return
		
		# Format the data as dictionaries with all four fields
		dialog_data = [
			{"EventLabel": label, "Time (s)": time, "Frame": frame, "ID (µm)": idval}
			for label, time, frame, idval in self.event_table_data
		]
		
		dialog = ExcelMappingDialog(self, dialog_data)
		if dialog.exec_():
			self.excel_auto_path = dialog.excel_path
			self.excel_auto_column = dialog.column_selector.currentText()

	def toggle_grid(self):
		self.grid_visible = not self.grid_visible
		if self.grid_visible:
			self.ax.grid(True, color='#CCC')
		else:
			self.ax.grid(False)
		self.canvas.draw_idle()


# [L] ========================= PlotStyleDialog =========================
from PyQt5.QtWidgets import (
	QDialog, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QSpinBox,
	QCheckBox, QPushButton, QFormLayout
)

class PlotStyleDialog(QDialog):
	def __init__(self, parent=None):
		super().__init__(parent)
		self.setWindowTitle("Plot Style Editor")
		self.setMinimumWidth(400)

		self.tabs = QTabWidget()
		main_layout = QVBoxLayout()
		main_layout.addWidget(self.tabs)
		self.setLayout(main_layout)

		# ===== Bottom OK / Apply / Cancel =====
		btn_row = QHBoxLayout()
		btn_row.setContentsMargins(10, 4, 10, 10)
		
		self.ok_btn = QPushButton("OK")
		self.cancel_btn = QPushButton("Cancel")
		self.apply_btn = QPushButton("Apply")
		
		self.ok_btn.clicked.connect(self.accept)
		self.cancel_btn.clicked.connect(self.reject)
		self.apply_btn.clicked.connect(self.handle_apply_all)
		
		btn_row.addStretch()
		btn_row.addWidget(self.apply_btn)
		btn_row.addWidget(self.cancel_btn)
		btn_row.addWidget(self.ok_btn)
		
		main_layout.addLayout(btn_row)

		# Track settings per tab
		self.init_axis_tab()
		self.init_tick_tab()
		self.init_event_tab()
		self.init_pin_tab()
		self.init_line_tab()

	def init_axis_tab(self):
		tab = QWidget()
		layout = QVBoxLayout(tab)
		form = QFormLayout()

		self.axis_font_size = QSpinBox()
		self.axis_font_size.setRange(6, 32)
		self.axis_font_size.setValue(14)

		self.axis_font_family = QComboBox()
		self.axis_font_family.addItems(["Arial", "Helvetica", "Times New Roman", "Courier", "Verdana"])

		self.axis_bold = QCheckBox("Bold")
		self.axis_italic = QCheckBox("Italic")

		form.addRow("Font Size:", self.axis_font_size)
		form.addRow("Font Family:", self.axis_font_family)
		form.addRow("", self.axis_bold)
		form.addRow("", self.axis_italic)

		layout.addLayout(form)
		layout.addLayout(self.button_row('axis'))
		self.tabs.addTab(tab, "Axis Titles")

	def init_tick_tab(self):
		tab = QWidget()
		layout = QVBoxLayout(tab)
		form = QFormLayout()

		self.tick_font_size = QSpinBox()
		self.tick_font_size.setRange(6, 32)
		self.tick_font_size.setValue(12)

		form.addRow("Tick Label Font Size:", self.tick_font_size)

		layout.addLayout(form)
		layout.addLayout(self.button_row('tick'))
		self.tabs.addTab(tab, "Tick Labels")

	def init_event_tab(self):
		tab = QWidget()
		layout = QVBoxLayout(tab)
		form = QFormLayout()

		self.event_font_size = QSpinBox()
		self.event_font_size.setRange(6, 32)
		self.event_font_size.setValue(10)

		self.event_font_family = QComboBox()
		self.event_font_family.addItems(["Arial", "Helvetica", "Times New Roman", "Courier", "Verdana"])

		self.event_bold = QCheckBox("Bold")
		self.event_italic = QCheckBox("Italic")

		form.addRow("Font Size:", self.event_font_size)
		form.addRow("Font Family:", self.event_font_family)
		form.addRow("", self.event_bold)
		form.addRow("", self.event_italic)

		layout.addLayout(form)
		layout.addLayout(self.button_row('event'))
		self.tabs.addTab(tab, "Event Labels")

	def init_pin_tab(self):
		tab = QWidget()
		layout = QVBoxLayout(tab)
		form = QFormLayout()

		self.pin_font_size = QSpinBox()
		self.pin_font_size.setRange(6, 32)
		self.pin_font_size.setValue(10)

		self.pin_font_family = QComboBox()
		self.pin_font_family.addItems(["Arial", "Helvetica", "Times New Roman", "Courier", "Verdana"])

		self.pin_bold = QCheckBox("Bold")
		self.pin_italic = QCheckBox("Italic")

		self.pin_size = QSpinBox()
		self.pin_size.setRange(2, 20)
		self.pin_size.setValue(6)

		form.addRow("Font Size:", self.pin_font_size)
		form.addRow("Font Family:", self.pin_font_family)
		form.addRow("", self.pin_bold)
		form.addRow("", self.pin_italic)
		form.addRow("Marker Size:", self.pin_size)

		layout.addLayout(form)
		layout.addLayout(self.button_row('pin'))
		self.tabs.addTab(tab, "Pinned Labels")

	def init_line_tab(self):
		tab = QWidget()
		layout = QVBoxLayout(tab)
		form = QFormLayout()

		self.line_width = QSpinBox()
		self.line_width.setRange(1, 10)
		self.line_width.setValue(2)

		form.addRow("Trace Line Width:", self.line_width)
		layout.addLayout(form)
		layout.addLayout(self.button_row('line'))
		self.tabs.addTab(tab, "Trace Style")

	def button_row(self, section):
		layout = QHBoxLayout()
		apply_btn = QPushButton("Apply")
		default_btn = QPushButton("Default")
	
		apply_btn.clicked.connect(lambda: self.handle_apply_tab(section))
		default_btn.clicked.connect(lambda: self.reset_defaults(section))
	
		layout.addStretch()
		layout.addWidget(apply_btn)
		layout.addWidget(default_btn)
		return layout
	
	def handle_apply_tab(self, section):
		# Only reapply current tab settings (optional expansion in future)
		if hasattr(self.parent(), "apply_plot_style"):
			self.parent().apply_plot_style(self.get_style())

	def handle_apply_all(self):
		if hasattr(self.parent(), "apply_plot_style"):
			self.parent().apply_plot_style(self.get_style())

	def reset_defaults(self, section):
		if section == 'axis':
			self.axis_font_size.setValue(14)
			self.axis_font_family.setCurrentText("Arial")
			self.axis_bold.setChecked(False)
			self.axis_italic.setChecked(False)
		elif section == 'tick':
			self.tick_font_size.setValue(12)
		elif section == 'event':
			self.event_font_size.setValue(10)
			self.event_font_family.setCurrentText("Arial")
			self.event_bold.setChecked(False)
			self.event_italic.setChecked(False)
		elif section == 'pin':
			self.pin_font_size.setValue(10)
			self.pin_font_family.setCurrentText("Arial")
			self.pin_bold.setChecked(False)
			self.pin_italic.setChecked(False)
			self.pin_size.setValue(6)
		elif section == 'line':
			self.line_width.setValue(2)

	def get_style(self):
		return {
			"axis_font_size": self.axis_font_size.value(),
			"axis_font_family": self.axis_font_family.currentText(),
			"axis_bold": self.axis_bold.isChecked(),
			"axis_italic": self.axis_italic.isChecked(),

			"tick_font_size": self.tick_font_size.value(),

			"event_font_size": self.event_font_size.value(),
			"event_font_family": self.event_font_family.currentText(),
			"event_bold": self.event_bold.isChecked(),
			"event_italic": self.event_italic.isChecked(),

			"pin_font_size": self.pin_font_size.value(),
			"pin_font_family": self.pin_font_family.currentText(),
			"pin_bold": self.pin_bold.isChecked(),
			"pin_italic": self.pin_italic.isChecked(),
			"pin_size": self.pin_size.value(),

			"line_width": self.line_width.value()
		}