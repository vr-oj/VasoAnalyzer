from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSlider, QTableWidget,
    QTableWidgetItem, QAbstractItemView, QPushButton, QFileDialog, QToolButton, QMessageBox
)
from PyQt5.QtWidgets import QLabel
from PyQt5.QtGui import QIcon
from PyQt5.QtCore import Qt, QSize
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas, NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
import pickle
import numpy as np
import os

from vasoanalyzer.trace_loader import load_trace
from vasoanalyzer.event_loader import load_events


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
                "Zoom: Draw box to zoom in"
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
            btn.setIcon(QIcon(self.window().icon_path("Customize:edit_axis_ranges.svg")))
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
            save_btn.setToolTip("Save As… Export high-res plot")
            save_btn.setIcon(QIcon(self.window().icon_path("Save.svg")))
            save_btn.triggered.disconnect()
            save_btn.triggered.connect(self._export_high_res_plot)

        # --- Load Button ---
        self.load_btn = QPushButton("📂 Load Trace + Events")
        self.load_btn.clicked.connect(self._on_load)

        # --- Axes ---
        self.ax = self.fig.add_subplot(111)

        # --- Pan Slider ---
        self.scroll_slider = QSlider(Qt.Horizontal)
        self.scroll_slider.setMinimum(0)
        self.scroll_slider.setMaximum(1000)
        self.scroll_slider.setSingleStep(1)
        self.scroll_slider.valueChanged.connect(self.scroll_plot)
        self.scroll_slider.hide()

        # --- Event Table (3 columns) ---
        self.event_table = QTableWidget()
        self.event_table.setColumnCount(3)
        self.event_table.setHorizontalHeaderLabels(["Event", "Time (s)", "ID (µm)"])
        self.event_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.event_table.setSelectionBehavior(QAbstractItemView.SelectRows)

        # --- Layout ---
        main_layout = QVBoxLayout(self)
        # Control row: toolbar + load
        control = QHBoxLayout()
        control.setContentsMargins(0,0,0,0)
        control.setSpacing(8)
        control.addWidget(self.toolbar)
        control.addWidget(self.load_btn)
        control.addStretch()
        main_layout.addLayout(control)
        # Plot and slider
        plot_layout = QVBoxLayout()
        plot_layout.addWidget(self.canvas)
        plot_layout.addWidget(self.scroll_slider)
        # Combine with table
        row = QHBoxLayout()
        row.addLayout(plot_layout, 4)
        row.addWidget(self.event_table, 1)
        main_layout.addLayout(row)

        # — Hover Label (exact same logic as main view) —
        self.hover_label = QLabel("", self)
        self.hover_label.setStyleSheet("""
            background-color: rgba(255, 255, 255, 220);
            border: 1px solid #888;
            border-radius: 5px;
            padding: 2px 6px;
            font-size: 12px;
        """)
        self.hover_label.hide()

        # connect hover & table‐click events
        self.canvas.mpl_connect("motion_notify_event", self.update_hover_label)
        self.event_table.cellClicked.connect(self.on_table_row_clicked)

        # Hook draw event
        self.canvas.mpl_connect("draw_event", self.sync_slider_with_plot)
        # Only reposition labels on mouse release, not every draw
        self.canvas.mpl_connect("button_release_event", self.update_event_label_positions)


        # State
        self.trace_data = None
        self.event_labels = []
        self.event_times = []
        self.event_table_data = []
        self.slider_marker = None
        self.grid_visible = True
        
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
        for pin in getattr(self, 'pins', []):
            try:
                pin.remove()
            except Exception:
                pass
        self.pins = []

    def _on_load(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Trace File", "", "CSV Files (*.csv)"
        )
        if not file_path:
            return
        df = load_trace(file_path)
        base = os.path.splitext(os.path.basename(file_path))[0]
        evp = os.path.join(os.path.dirname(file_path), f"{base}_table.csv")
        events = []
        if os.path.exists(evp):
            try:
                lbls, tms, _ = load_events(evp)
                events = list(zip(lbls, tms))
            except:
                pass
        # delegate to panel loader
        self.load_trace_and_events(df, events)
        self.load_trace_and_events

    def load_trace_and_events(self, trace_df, events):
        """
        Load a pandas DataFrame and associated events into this panel.
        """
        self.trace_data = trace_df
        if events:
            self.event_labels, self.event_times = zip(*events)
        else:
            self.event_labels, self.event_times = [], []
        # Refresh view
        self.update_plot()
        self.populate_table()
        self.update_scroll_slider()

    def update_plot(self):
        """Plot the trace and events on the canvas."""
        self.ax.clear()
        self.event_text_objects = []                  # ← reset the list
        t = self.trace_data["Time (s)"]
        d = self.trace_data["Inner Diameter"]
        self.ax.plot(t, d, "k-", linewidth=1.5)
        self.ax.set_xlabel("Time (s)")
        self.ax.set_ylabel("Inner Diameter (µm)")
        self.ax.grid(self.grid_visible)

        for lbl, t_evt in zip(self.event_labels, self.event_times):
            self.ax.axvline(t_evt, color="black", linestyle="--", linewidth=0.8)
            txt = self.ax.text(
                t_evt, 0, lbl,
                rotation=90,
                verticalalignment="top",
                horizontalalignment="right",
                fontsize=8,
                clip_on=True,
            )
            self.event_text_objects.append((txt, t_evt))  # ← store both text object and its x
        self.canvas.draw_idle()

    def populate_table(self):
        # Populate the event table with Event, Time, ID
        self.event_table_data = []
        # assume an offset of 2 seconds
        offset = 2.0
        times = self.trace_data["Time (s)"].values
        diam  = self.trace_data["Inner Diameter"].values
        self.event_table_data = []
        for i, (lbl, t_evt) in enumerate(zip(self.event_labels, self.event_times)):
            if i < len(self.event_times) - 1:
                t_sample = self.event_times[i+1] - offset
                idx = np.argmin(np.abs(times - t_sample))
            else:
                # for the last event just use the last sample
                idx = -1
            sampled_dia = float(diam[idx])
            self.event_table_data.append((lbl, round(t_evt,2), round(sampled_dia,2)))

        self.event_table.setRowCount(len(self.event_table_data))
        for row, (lbl, t_evt, idval) in enumerate(self.event_table_data):
            self.event_table.setItem(row, 0, QTableWidgetItem(lbl))
            self.event_table.setItem(row, 1, QTableWidgetItem(str(t_evt)))
            self.event_table.setItem(row, 2, QTableWidgetItem(str(idval)))

    def sync_slider_with_plot(self, event=None):
        if self.trace_data is None:
            return
        full = self.trace_data["Time (s)"]
        tmin, tmax = full.min(), full.max()
        xmin, xmax = self.ax.get_xlim()
        window = xmax - xmin
        scroll_max = tmax - window
        val = 0 if scroll_max <= tmin else np.interp(
            xmin, [tmin, scroll_max], [0, 1000]
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
            main.open_axis_settings_dialog_for(self.ax, self.canvas)

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
        for txt, _ in getattr(self, 'event_text_objects', []):
            txt.set_fontsize(style.get("event_font_size", 10))
            txt.set_fontname(style.get("event_font_family", "Arial"))
            txt.set_fontstyle(
                "italic" if style.get("event_italic") else "normal"
            )
            txt.set_fontweight(
                "bold" if style.get("event_bold") else "normal"
            )
        # Line width
        if self.ax.lines:
            self.ax.lines[0].set_linewidth(style.get("line_width", 2))
        self.canvas.draw_idle()


    def update_hover_label(self, event):
        """Show Time & ID exactly under cursor, like main view."""
        if event.inaxes != self.ax or self.trace_data is None or event.xdata is None:
            self.hover_label.hide()
            return

        # find nearest sample
        times = self.trace_data["Time (s)"].values
        diams = self.trace_data["Inner Diameter"].values
        idx = int(np.argmin(np.abs(times - event.xdata)))
        t_near = times[idx]
        d_near = diams[idx]

        self.hover_label.setText(f"Time: {t_near:.2f} s\nID: {d_near:.2f} µm")

        # now position it using the canvas geometry + cursor offset
        cr = self.canvas.geometry()
        # event.guiEvent.pos() is QPoint relative to canvas
        gx = cr.left() + event.guiEvent.pos().x()
        gy = cr.top()  + event.guiEvent.pos().y()
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

    
    def _toggle_grid(self):
        self.grid_visible = not self.grid_visible
        self.ax.grid(self.grid_visible, color="#CCC")
        self.canvas.draw_idle()

    def _export_high_res_plot(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save High-Resolution Plot",
            "", "TIFF Image (*.tiff);;SVG Vector (*.svg)"
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
        times  = state.get("event_times", [])
        events = list(zip(labels, times))
        if trace_df is not None:
            self.load_trace_and_events(trace_df, events)

        # 2) Restore table contents if present
        ev_table = state.get("event_table_data", None)
        if ev_table is not None:
            self.event_table_data = ev_table
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
