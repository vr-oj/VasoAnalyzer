from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSlider,
    QTableWidget,
    QTableWidgetItem,
    QAbstractItemView,
    QPushButton,
    QFileDialog,
    QMenu,
    QToolButton,
    QMessageBox,
    QHeaderView,
    QLabel,
)
from PyQt5.QtGui import QIcon, QImage, QPixmap
from PyQt5.QtCore import Qt, QSize
from matplotlib.backends.backend_qt5agg import (
    FigureCanvasQTAgg as FigureCanvas,
    NavigationToolbar2QT as NavigationToolbar,
)
from matplotlib.figure import Figure
import pickle
import numpy as np
import os

from vasoanalyzer.trace_event_loader import load_trace_and_events


class DataViewPanel(QWidget):
    """A single plot + pan‑slider + event table view with full matplotlib toolbar."""

    def __init__(self, parent=None):
        super().__init__(parent)

        # --- Matplotlib Figure & Canvas ---
        self.fig = Figure(facecolor="white")
        self.canvas = FigureCanvas(self.fig)

        # --- Toolbar ---
        self.toolbar = NavigationToolbar(self.canvas, self)
        self.toolbar.setIconSize(QSize(18, 18))

        # Customize toolbar (copying logic from gui.py)
        self.toolbar.setStyleSheet(
            """
            QToolBar { background-color: #F0F0F0; padding: 2px; border: none; }
            """
        )
        if hasattr(self.toolbar, "coordinates"):
            self.toolbar.coordinates = lambda *args, **kwargs: None
            for act in self.toolbar.actions():
                if act.text() == "":
                    self.toolbar.removeAction(act)
        visible = [a for a in self.toolbar.actions() if not a.icon().isNull()]
        if len(visible) >= 8:
            tooltips = [
                "Home: Reset zoom and pan",
                "Back: Previous view",
                "Forward: Next view",
                "Pan: Click and drag plot",
                "Zoom: Draw box to zoom in",
            ]
            icons = [
                "Home.svg",
                "Back.svg",
                "Forward.svg",
                "Pan.svg",
                "Zoom.svg",
            ]
            for btn, tip, icon in zip(visible[:5], tooltips, icons):
                btn.setToolTip(tip)
                btn.setIcon(QIcon(self.window().icon_path(icon)))
            # Configure subplot layout
            btn = visible[5]
            btn.setToolTip("Configure subplot layout")
            btn.setIcon(QIcon(self.window().icon_path("Subplots.svg")))
            btn.triggered.disconnect()
            btn.triggered.connect(self.toolbar.configure_subplots)
            # Edit parameters
            btn = visible[6]
            btn.setToolTip("Edit axis ranges and titles")
            btn.setIcon(
                QIcon(self.window().icon_path("Customize:edit_axis_ranges.svg"))
            )
            btn.triggered.disconnect()
            btn.triggered.connect(self._open_axis_dialog)
            # Inject Plot Style button
            style_btn = QToolButton()
            style_btn.setIcon(QIcon(self.window().icon_path("Aa.svg")))
            style_btn.setToolTip("Customize plot fonts and layout")
            style_btn.clicked.connect(self._open_plot_style)
            self.toolbar.insertWidget(visible[7], style_btn)
            # Inject Grid Toggle
            grid_btn = QToolButton()
            grid_btn.setIcon(QIcon(self.window().icon_path("Grid.svg")))
            grid_btn.setToolTip("Toggle grid visibility")
            grid_btn.setCheckable(True)
            grid_btn.setChecked(True)
            grid_btn.clicked.connect(self._toggle_grid)
            self.toolbar.insertWidget(visible[7], grid_btn)
            # Override save
            save_btn = visible[7]
            save_btn.setToolTip("Save As… Export plot or save to N")
            save_btn.setIcon(QIcon(self.window().icon_path("Save.svg")))
            save_btn.triggered.disconnect()
            save_btn.triggered.connect(self.window().show_save_menu)

        # --- Load Buttons ---
        self.load_btn = QPushButton("📂 Load Trace + Events")
        self.load_btn.clicked.connect(self._on_load)

        self.load_tiff_btn = QPushButton("🖼️ Load _Result.tiff")
        self.load_tiff_btn.clicked.connect(self.load_snapshot)

        # --- Axes ---
        self.ax = self.fig.add_subplot(111)

        # --- Pan Slider ---
        self.scroll_slider = QSlider(Qt.Horizontal)
        self.scroll_slider.setMinimum(0)
        self.scroll_slider.setMaximum(1000)
        self.scroll_slider.setSingleStep(1)
        self.scroll_slider.valueChanged.connect(self.scroll_plot)
        self.scroll_slider.hide()

        # --- Event Table ---
        # Mirror main view defaults: Event, Time, ID, Frame
        self.event_table = QTableWidget()
        self.event_table.setColumnCount(4)
        self.event_table.setHorizontalHeaderLabels(
            ["Event", "Time (s)", "ID (µm)", "Frame"]
        )
        self.event_table.setEditTriggers(QAbstractItemView.DoubleClicked)
        self.event_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.event_table.itemChanged.connect(self.handle_table_edit)
        self.event_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.event_table.customContextMenuRequested.connect(
            self.show_event_table_context_menu
        )

        header = self.event_table.horizontalHeader()
        header.setStretchLastSection(False)
        for i in range(4):
            header.setSectionResizeMode(i, QHeaderView.Interactive)
        header.setDefaultSectionSize(100)

        # --- Layout ---
        main_layout = QVBoxLayout(self)
        # Control row: toolbar + load
        control = QHBoxLayout()
        control.setContentsMargins(0, 0, 0, 0)
        control.setSpacing(8)
        control.addWidget(self.toolbar)
        control.addWidget(self.load_btn)
        control.addWidget(self.load_tiff_btn)
        control.addStretch()
        main_layout.addLayout(control)
        # Plot and slider
        plot_layout = QVBoxLayout()
        plot_layout.addWidget(self.canvas)
        plot_layout.addWidget(self.scroll_slider)

        # Snapshot viewer
        self.snapshot_label = QLabel("Snapshot will appear here")
        self.snapshot_label.setAlignment(Qt.AlignCenter)
        self.snapshot_label.setFixedSize(400, 250)
        self.snapshot_label.hide()

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setMinimum(0)
        self.slider.valueChanged.connect(self.change_frame)
        self.slider.hide()

        snapshot_layout = QVBoxLayout()
        snapshot_layout.addWidget(self.snapshot_label)
        snapshot_layout.addWidget(self.slider)

        right_layout = QVBoxLayout()
        right_layout.addLayout(snapshot_layout)
        right_layout.addWidget(self.event_table)

        # Combine plot with right column
        row = QHBoxLayout()
        row.addLayout(plot_layout, 4)
        row.addLayout(right_layout, 1)
        main_layout.addLayout(row)

        # — Hover Label (exact same logic as main view) —
        self.hover_label = QLabel("", self)
        self.hover_label.setStyleSheet(
            """
            background-color: rgba(255, 255, 255, 220);
            border: 1px solid #888;
            border-radius: 5px;
            padding: 2px 6px;
            font-size: 12px;
        """
        )
        self.hover_label.hide()

        # connect hover & table‐click events
        self.canvas.mpl_connect("motion_notify_event", self.update_hover_label)
        self.event_table.cellClicked.connect(self.on_table_row_clicked)
        self.canvas.mpl_connect("button_press_event", self.handle_click_on_plot)

        # Hook draw event
        self.canvas.mpl_connect("draw_event", self.sync_slider_with_plot)
        # Only reposition labels on mouse release, not every draw
        self.canvas.mpl_connect(
            "button_release_event", self.update_event_label_positions
        )

        # State
        self.trace_data = None
        self.event_labels = []
        self.event_times = []
        self.event_frames = []
        self.event_table_data = []
        self.ax2 = None
        self.slider_marker = None
        self.grid_visible = True
        self.pins = []

        self.recording_interval = 0.14
        self.snapshot_frames = []
        self.frame_times = []
        self.frame_trace_indices = []
        self.current_frame = 0

        # Dual Clearing
        self._original_title = self.ax.get_title()

    def clear_data(self):
        """
        Clear this panel's plot, table, and any pins/highlights.
        """
        # Clear plot
        self.ax.clear()
        self.ax.set_title(self._original_title)
        # Apply current or default style after drawing
        main = self.window()
        if hasattr(main, "get_current_plot_style"):
            style = main.get_current_plot_style()
        else:
            from .gui import DEFAULT_STYLE

            style = DEFAULT_STYLE
        self.apply_plot_style(style)

        # Clear events table
        self.event_table.setRowCount(0)

        # Clear pins/highlights
        for marker, label in getattr(self, "pins", []):
            try:
                marker.remove()
                label.remove()
            except Exception:
                pass
        self.pins = []

    def _on_load(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Trace File", "", "CSV Files (*.csv)"
        )
        if not file_path:
            return
        df, labels, times, frames, _diam, _od = load_trace_and_events(file_path)
        events = list(zip(labels, times))
        # delegate to panel loader
        self.load_trace_and_events(df, events, frames)

    def load_trace_and_events(self, trace_df, events, frames=None):
        """
        Load a pandas DataFrame and associated events into this panel.
        """
        self.trace_data = trace_df
        if events:
            self.event_labels, self.event_times = zip(*events)
        else:
            self.event_labels, self.event_times = [], []
        self.event_frames = list(frames) if frames is not None else []
        # Refresh view
        self.update_plot()
        self.populate_table()
        self.update_scroll_slider()
        self.compute_frame_trace_indices()

    def update_plot(self):
        """Plot the trace and events on the canvas."""
        self.ax.clear()
        if self.ax2:
            self.ax2.remove()
            self.ax2 = None

        self.event_text_objects = []  # reset the list

        t = self.trace_data["Time (s)"]
        d = self.trace_data["Inner Diameter"]
        self.ax.plot(t, d, "k-", linewidth=1.5)
        self.ax.set_xlabel("Time (s)")
        self.ax.set_ylabel("Inner Diameter (µm)")
        self.ax.grid(self.grid_visible)

        if "Outer Diameter" in self.trace_data.columns:
            od = self.trace_data["Outer Diameter"]
            self.ax2 = self.ax.twinx()
            self.ax2.plot(t, od, color="tab:orange", linewidth=1.2)
            self.ax2.set_ylabel("Outer Diameter (µm)")
            self.ax2.grid(False)

        for lbl, t_evt in zip(self.event_labels, self.event_times):
            self.ax.axvline(t_evt, color="black", linestyle="--", linewidth=0.8)
            txt = self.ax.text(
                t_evt,
                0,
                lbl,
                rotation=90,
                verticalalignment="top",
                horizontalalignment="right",
                fontsize=8,
                clip_on=True,
            )
            self.event_text_objects.append(
                (txt, t_evt)
            )  # ← store both text object and its x
        self.canvas.draw_idle()

    def populate_table(self):
        # Populate the event table with Event, Time, ID, (OD), Frame
        self.event_table.blockSignals(True)
        self.event_table_data = []
        offset = 2.0
        times = self.trace_data["Time (s)"].to_numpy()
        diam_i = self.trace_data["Inner Diameter"].to_numpy()
        diam_o = (
            self.trace_data["Outer Diameter"].to_numpy()
            if "Outer Diameter" in self.trace_data.columns
            else None
        )

        for i, (lbl, t_evt) in enumerate(zip(self.event_labels, self.event_times)):
            if i < len(self.event_times) - 1:
                t_sample = self.event_times[i + 1] - offset
                idx = np.argmin(np.abs(times - t_sample))
            else:
                idx = len(times) - 1

            id_val = float(diam_i[idx])
            frame = int(self.event_frames[i]) if i < len(self.event_frames) else idx
            if diam_o is not None:
                od_val = float(diam_o[idx])
                self.event_table_data.append(
                    (lbl, round(t_evt, 2), round(id_val, 2), round(od_val, 2), frame)
                )
            else:
                self.event_table_data.append(
                    (lbl, round(t_evt, 2), round(id_val, 2), frame)
                )

        has_od = diam_o is not None
        header = ["Event", "Time (s)", "ID (µm)"]
        if has_od:
            header.extend(["OD (µm)", "Frame"])
        else:
            header.append("Frame")

        self.event_table.setColumnCount(len(header))
        self.event_table.setHorizontalHeaderLabels(header)
        self.event_table.setRowCount(len(self.event_table_data))
        for row, data in enumerate(self.event_table_data):
            for col, val in enumerate(data):
                self.event_table.setItem(row, col, QTableWidgetItem(str(val)))

        # adjust header sections
        header_widget = self.event_table.horizontalHeader()
        for i in range(len(header)):
            header_widget.setSectionResizeMode(i, QHeaderView.Interactive)
        self.event_table.blockSignals(False)

    def sync_slider_with_plot(self, event=None):
        if self.trace_data is None:
            return
        full = self.trace_data["Time (s)"]
        tmin, tmax = full.min(), full.max()
        xmin, xmax = self.ax.get_xlim()
        window = xmax - xmin
        scroll_max = tmax - window
        val = (
            0 if scroll_max <= tmin else np.interp(xmin, [tmin, scroll_max], [0, 1000])
        )
        self.scroll_slider.blockSignals(True)
        self.scroll_slider.setValue(int(val))
        self.scroll_slider.blockSignals(False)

    def scroll_plot(self):
        if self.trace_data is None:
            return
        full = self.trace_data["Time (s)"]
        tmin, tmax = full.min(), full.max()
        xmin, xmax = self.ax.get_xlim()
        window = xmax - xmin
        frac = self.scroll_slider.value() / 1000.0
        new_left = tmin + (tmax - tmin - window) * frac
        self.ax.set_xlim(new_left, new_left + window)
        self.canvas.draw_idle()

    def update_event_label_positions(self, event=None):
        """Reposition event labels at the top of the current y‐axis."""
        if not hasattr(self, "event_text_objects"):
            return
        y_min, y_max = self.ax.get_ylim()
        # push them just below the top margin
        y_top = min(y_max - (y_max - y_min) * 0.05, y_max * 0.95)
        for txt, x in self.event_text_objects:
            txt.set_position((x, y_top))
        self.canvas.draw_idle()

    def update_scroll_slider(self):
        if self.trace_data is None:
            self.scroll_slider.hide()
            return
        full = self.trace_data["Time (s)"]
        tmin, tmax = full.min(), full.max()
        window = self.ax.get_xlim()[1] - self.ax.get_xlim()[0]
        if window < (tmax - tmin):
            self.scroll_slider.show()
        else:
            self.scroll_slider.hide()

    def _open_plot_style(self):
        """Delegate to the main window's style editor for consistency."""
        main = self.window()
        if hasattr(main, "open_plot_style_editor_for"):
            main.open_plot_style_editor_for(
                self.ax,
                self.canvas,
                event_text_objects=getattr(self, "event_text_objects", None),
                pinned_points=getattr(self, "pins", None),
            )

    def _open_axis_dialog(self):
        main = self.window()
        if hasattr(main, "open_axis_settings_dialog_for"):
            main.open_axis_settings_dialog_for(self.ax, self.canvas, None)

    def apply_plot_style(self, style):
        """Apply style dictionary to this panel's plot."""
        # Axis Titles
        self.ax.xaxis.label.set_fontsize(style.get("axis_font_size", 14))
        self.ax.xaxis.label.set_fontname(style.get("axis_font_family", "Arial"))
        self.ax.xaxis.label.set_fontstyle(
            "italic" if style.get("axis_italic") else "normal"
        )
        self.ax.xaxis.label.set_fontweight(
            "bold" if style.get("axis_bold") else "normal"
        )
        self.ax.yaxis.label.set_fontsize(style.get("axis_font_size", 14))
        self.ax.yaxis.label.set_fontname(style.get("axis_font_family", "Arial"))
        self.ax.yaxis.label.set_fontstyle(
            "italic" if style.get("axis_italic") else "normal"
        )
        self.ax.yaxis.label.set_fontweight(
            "bold" if style.get("axis_bold") else "normal"
        )
        # Tick Labels
        self.ax.tick_params(axis="x", labelsize=style.get("tick_font_size", 12))
        self.ax.tick_params(axis="y", labelsize=style.get("tick_font_size", 12))
        # Event Labels
        for txt, _ in getattr(self, "event_text_objects", []):
            txt.set_fontsize(style.get("event_font_size", 10))
            txt.set_fontname(style.get("event_font_family", "Arial"))
            txt.set_fontstyle("italic" if style.get("event_italic") else "normal")
            txt.set_fontweight("bold" if style.get("event_bold") else "normal")
        # Line width
        if self.ax.lines:
            self.ax.lines[0].set_linewidth(style.get("line_width", 2))
        self.canvas.draw_idle()

    def update_hover_label(self, event):
        """Show Time & ID/OD exactly under cursor, like main view."""
        valid_axes = [self.ax]
        if self.ax2:
            valid_axes.append(self.ax2)
        if (
            event.inaxes not in valid_axes
            or self.trace_data is None
            or event.xdata is None
        ):
            self.hover_label.hide()
            return

        times = self.trace_data["Time (s)"].to_numpy()
        idx = int(np.argmin(np.abs(times - event.xdata)))
        t_near = times[idx]

        if event.inaxes == self.ax2 and "Outer Diameter" in self.trace_data.columns:
            val = self.trace_data["Outer Diameter"].to_numpy()[idx]
            label = "OD"
        else:
            val = self.trace_data["Inner Diameter"].to_numpy()[idx]
            label = "ID"

        self.hover_label.setText(f"Time: {t_near:.2f} s\n{label}: {val:.2f} µm")

        # now position it using the canvas geometry + cursor offset
        cr = self.canvas.geometry()
        # event.guiEvent.pos() is QPoint relative to canvas
        gx = cr.left() + event.guiEvent.pos().x()
        gy = cr.top() + event.guiEvent.pos().y()
        self.hover_label.move(int(gx + 10), int(gy - 30))
        self.hover_label.adjustSize()
        self.hover_label.show()

    def on_table_row_clicked(self, row, col):
        """Draw a blue vertical line at the selected event time."""
        if not self.event_table_data:
            return

        # remove any prior blue line
        if hasattr(self, "_selected_marker") and self._selected_marker:
            self._selected_marker.remove()

        t = self.event_table_data[row][1]  # your (label, time, id) tuple
        self._selected_marker = self.ax.axvline(
            x=t, color="blue", linestyle="--", linewidth=1.2
        )
        self.canvas.draw_idle()

    def handle_table_edit(self, item):
        row = item.row()
        col = item.column()

        if col != 2:
            self.populate_table()
            return

        try:
            new_val = float(item.text())
        except ValueError:
            QMessageBox.warning(self, "Invalid Input", "Please enter a valid number.")
            self.populate_table()
            return

        has_od = (
            self.trace_data is not None and "Outer Diameter" in self.trace_data.columns
        )
        if has_od:
            od_val = self.event_table_data[row][3]
            frame = self.event_table_data[row][4]
            self.event_table_data[row] = (
                self.event_table_data[row][0],
                self.event_table_data[row][1],
                round(new_val, 2),
                od_val,
                frame,
            )
        else:
            frame = self.event_table_data[row][3]
            self.event_table_data[row] = (
                self.event_table_data[row][0],
                self.event_table_data[row][1],
                round(new_val, 2),
                frame,
            )
        self.populate_table()

    def show_event_table_context_menu(self, pos):
        index = self.event_table.indexAt(pos)
        if not index.isValid():
            return
        row = index.row()

        menu = QMenu(self)
        jump_action = menu.addAction("Jump to Event on Plot")
        delete_action = menu.addAction("Delete Event")
        action = menu.exec_(self.event_table.viewport().mapToGlobal(pos))

        if action == jump_action:
            self.on_table_row_clicked(row, 0)
        elif action == delete_action:
            del self.event_labels[row]
            del self.event_times[row]
            del self.event_table_data[row]
            self.populate_table()
            self.update_plot()

    def handle_click_on_plot(self, event):
        if event.inaxes != self.ax or self.trace_data is None:
            return

        x = event.xdata
        if x is None:
            return

        if event.button == 1 and not self.toolbar.mode:
            times = self.trace_data["Time (s)"].to_numpy()
            idx = int(np.argmin(np.abs(times - x)))
            y = self.trace_data["Inner Diameter"].to_numpy()[idx]
            marker = self.ax.plot(x, y, "ro", markersize=6)[0]
            label = self.ax.annotate(
                f"{x:.2f} s\n{y:.1f} µm",
                xy=(x, y),
                xytext=(6, 6),
                textcoords="offset points",
                bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#000", lw=1),
                fontsize=8,
            )
            self.pins.append((marker, label))
            self.canvas.draw_idle()
        elif event.button == 3:
            click_x, click_y = event.x, event.y
            for marker, label in list(self.pins):
                data_x = marker.get_xdata()[0]
                data_y = marker.get_ydata()[0]
                px, py = self.ax.transData.transform((data_x, data_y))
                if np.hypot(px - click_x, py - click_y) < 10:
                    marker.remove()
                    label.remove()
                    self.pins.remove((marker, label))
                    self.canvas.draw_idle()
                    return

    def _toggle_grid(self):
        self.grid_visible = not self.grid_visible
        self.ax.grid(self.grid_visible, color="#CCC")
        if self.ax2:
            self.ax2.grid(self.grid_visible, color="#CCC")
        self.canvas.draw_idle()

    # ------------------------------------------------------------------
    # Snapshot / TIFF handling

    def load_snapshot(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open Result TIFF", "", "TIFF Files (*.tif *.tiff)"
        )
        if not file_path:
            return
        try:
            from vasoanalyzer.tiff_loader import load_tiff_preview

            frames, _ = load_tiff_preview(file_path)
            self.load_snapshots(frames)
        except Exception as e:
            QMessageBox.critical(self, "TIFF Load Error", f"Failed to load TIFF:\n{e}")

    def load_snapshots(self, stack):
        self.snapshot_frames = [f for f in stack if f is not None and f.size > 0]
        if not self.snapshot_frames:
            QMessageBox.warning(self, "TIFF", "No valid frames found in TIFF.")
            return

        self.frame_times = [i * self.recording_interval for i in range(len(self.snapshot_frames))]
        self.compute_frame_trace_indices()

        self.slider.setMinimum(0)
        self.slider.setMaximum(len(self.snapshot_frames) - 1)
        self.slider.setValue(0)
        self.slider.show()
        self.snapshot_label.show()
        self.display_frame(0)
        self.update_slider_marker()

    def compute_frame_trace_indices(self):
        if self.trace_data is None or not self.frame_times:
            self.frame_trace_indices = []
            return

        t_trace = self.trace_data["Time (s)"].to_numpy()
        frame_times = np.asarray(self.frame_times, dtype=float)

        if len(frame_times) > 1:
            dt_trace = float(t_trace[-1]) - float(t_trace[0])
            dt_frames = float(frame_times[-1]) - float(frame_times[0])
            scale = dt_trace / dt_frames if dt_frames != 0 else 1.0
        else:
            scale = 1.0

        adjusted = (frame_times - frame_times[0]) * scale + t_trace[0]
        idx = np.searchsorted(t_trace, adjusted, side="left")
        idx = np.clip(idx, 0, len(t_trace) - 1)
        self.frame_trace_indices = idx

    def change_frame(self):
        if not self.snapshot_frames:
            return

        idx = self.slider.value()
        self.current_frame = idx
        self.display_frame(idx)
        self.update_slider_marker()

    def display_frame(self, index):
        if not self.snapshot_frames:
            return

        if index < 0 or index >= len(self.snapshot_frames):
            return

        frame = self.snapshot_frames[index]
        try:
            if frame.ndim == 2:
                h, w = frame.shape
                img = QImage(frame.data, w, h, QImage.Format_Grayscale8)
            elif frame.ndim == 3 and frame.shape[2] == 3:
                h, w, _ = frame.shape
                img = QImage(frame.data, w, h, 3 * w, QImage.Format_RGB888)
            else:
                return

            target_width = self.event_table.viewport().width() or self.snapshot_label.width()
            pix = QPixmap.fromImage(img).scaledToWidth(target_width, Qt.SmoothTransformation)
            self.snapshot_label.setFixedSize(pix.width(), pix.height())
            self.snapshot_label.setPixmap(pix)
        except Exception:
            pass

    def update_slider_marker(self):
        if self.trace_data is None or not self.snapshot_frames:
            return

        idx = self.slider.value()
        if idx < len(self.frame_trace_indices):
            trace_idx = self.frame_trace_indices[idx]
            t_current = self.trace_data["Time (s)"].iat[trace_idx]
        else:
            t_current = idx * self.recording_interval

        if self.slider_marker is None:
            self.slider_marker = self.ax.axvline(
                x=t_current,
                color="red",
                linestyle="--",
                linewidth=1.5,
                label="TIFF Frame",
            )
        else:
            self.slider_marker.set_xdata([t_current, t_current])

        self.canvas.draw_idle()

    def _export_high_res_plot(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save High-Resolution Plot",
            "",
            "TIFF Image (*.tiff);;SVG Vector (*.svg)",
        )
        if file_path:
            ext = os.path.splitext(file_path)[1].lower()
            if ext == ".svg":
                self.fig.savefig(file_path, format="svg", bbox_inches="tight")
            else:
                self.fig.savefig(file_path, format="tiff", dpi=600, bbox_inches="tight")

    def load_pickle_session(self, file_path):
        """
        Load a .fig.pickle session into this panel:
        restores the trace, events, styling, axis limits, and table.
        """
        try:
            with open(file_path, "rb") as f:
                state = pickle.load(f)
        except Exception as e:
            QMessageBox.warning(self, "Load Failed", f"Could not read pickle:\n{e}")
            return

        # 1) Restore the trace & event lines
        trace_df = state.get("trace_data", None)
        labels = state.get("event_labels", [])
        times = state.get("event_times", [])
        frames = state.get("event_frames", None)
        events = list(zip(labels, times))
        if trace_df is not None:
            self.load_trace_and_events(trace_df, events, frames)

        # 2) Restore table contents if present
        ev_table = state.get("event_table_data", None)
        if ev_table is not None:
            self.event_table_data = ev_table
            if ev_table:
                f_idx = (
                    4 if len(ev_table[0]) == 5 else 3 if len(ev_table[0]) >= 4 else None
                )
                if f_idx is not None:
                    self.event_frames = [row[f_idx] for row in ev_table]
            self.populate_table()

        # 3) Restore plot style
        plot_style = state.get("plot_style", None)
        if plot_style:
            self.apply_plot_style(plot_style)

        # 4) Restore axis labels & limits
        self.ax.set_xlabel(state.get("xlabel", self.ax.get_xlabel()))
        self.ax.set_ylabel(state.get("ylabel", self.ax.get_ylabel()))
        self.ax.set_xlim(*state.get("xlim", self.ax.get_xlim()))
        self.ax.set_ylim(*state.get("ylim", self.ax.get_ylim()))

        # 5) Restore grid visibility
        self.grid_visible = state.get("grid_visible", self.grid_visible)
        self.ax.grid(self.grid_visible)

        self.canvas.draw_idle()


class DualViewWidget(QWidget):
    """Holds two DataViewPanels, stacked vertically."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.panelA = DataViewPanel(self)
        self.panelB = DataViewPanel(self)
        layout.addWidget(self.panelA)
        layout.addWidget(self.panelB)
