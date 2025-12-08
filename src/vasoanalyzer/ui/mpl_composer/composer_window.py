"""Pure Matplotlib Figure Composer Window - Phase 3 Complete.

This module implements the main composer UI using ONLY Matplotlib widgets
for all controls. Qt is used solely to host the Matplotlib canvas.

Features (Phase 3):
- Full annotation creation (text, box, arrow, line)
- Annotation selection and dragging
- Annotation property editor panel
- Multi-panel layout templates
- Export functionality
"""

from __future__ import annotations

import copy
import logging
import uuid
from typing import TYPE_CHECKING

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from matplotlib.widgets import Button, RadioButtons, Slider, TextBox
from PyQt5.QtWidgets import QFileDialog, QMainWindow, QMessageBox, QVBoxLayout, QWidget

from .renderer import render_figure, render_into_axes
from .specs import (
    AnnotationSpec,
    ExportSpec,
    FigureSpec,
    GraphInstance,
    GraphSpec,
    LayoutSpec,
    TraceBinding,
)
from .theme import PAGE_BG_COLOR, THEME

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from vasoanalyzer.core.trace_model import TraceModel

__all__ = ["PureMplFigureComposer"]

log = logging.getLogger(__name__)


class PureMplFigureComposer(QMainWindow):
    """Pure Matplotlib Figure Composer window with full annotation support."""

    def __init__(
        self,
        trace_model: TraceModel | None = None,
        parent=None,
        *,
        event_times: list[float] | None = None,
        event_labels: list[str] | None = None,
        event_colors: list[str] | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Pure Matplotlib Figure Composer")
        self.trace_model = trace_model
        self.event_times = event_times or []
        self.event_labels = event_labels or []
        self.event_colors = event_colors or []

        # Typography baseline
        mpl.rcParams["font.family"] = "DejaVu Sans"
        mpl.rcParams["font.size"] = 9

        # Undo/redo stacks
        self._undo_stack: list[FigureSpec] = []
        self._redo_stack: list[FigureSpec] = []
        self._max_undo = 50

        # Current spec (single source of truth)
        self.spec = self._create_default_spec()

        # Preview settings
        self.preview_dpi = 100
        self.zoom_factor = 1.0

        # Annotation interaction state
        self.annotation_mode: str | None = "select"
        self.selected_annotation_id: str | None = None
        self._drag_start: tuple[float, float] | None = None
        self._creating_annotation: AnnotationSpec | None = None
        self._suppress_size_events = False
        self._preview_axes_map: dict[str, Axes] = {}

        # UI widget references
        self.toolbar_buttons: dict[str, Button] = {}
        self._toolbar_base_colors: dict[str, str] = {}
        self.control_widgets: dict[str, any] = {}

        # Build UI
        self._setup_ui()
        self._connect_events()

        # Initial render
        self._push_undo()
        self._update_preview()

        # Set reasonable window size
        self.resize(1600, 1000)

    def _create_default_spec(self) -> FigureSpec:
        """Create a default FigureSpec for initialization."""
        if self.trace_model is not None:
            sample_id = "current_sample"
            trace_bindings = [TraceBinding(name="inner", kind="inner")]
            if self.trace_model.outer_full is not None:
                trace_bindings.append(TraceBinding(name="outer", kind="outer"))
        else:
            sample_id = "no_sample"
            trace_bindings = []

        graph_spec = GraphSpec(
            graph_id="graph1",
            name="Main Graph",
            sample_id=sample_id,
            trace_bindings=trace_bindings,
            x_label="Time (s)",
            y_label="Diameter (µm)",
        )

        graph_instance = GraphInstance(
            instance_id="inst1",
            graph_id="graph1",
            row=0,
            col=0,
        )

        layout_spec = LayoutSpec(
            width_in=5.9,  # ~150 mm
            height_in=3.0,
            graph_instances=[graph_instance],
            nrows=1,
            ncols=1,
        )

        export_spec = ExportSpec(
            format="pdf",
            dpi=600,
            preset_name="Single column (150 mm)",
        )

        return FigureSpec(
            graphs={"graph1": graph_spec},
            layout=layout_spec,
            export=export_spec,
        )

    def _setup_ui(self):
        """Set up the UI with Matplotlib widgets."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)

        # Create main UI figure
        self.ui_figure = Figure(figsize=(16, 10), dpi=100, facecolor=THEME["bg_window"])
        self.canvas = FigureCanvasQTAgg(self.ui_figure)
        layout.addWidget(self.canvas)

        # Layout grid (title, toolbar, page, controls, footer)
        self.ui_gs = self.ui_figure.add_gridspec(
            30,
            30,
            left=0.02,
            right=0.98,
            top=0.98,
            bottom=0.03,
            wspace=0.2,
            hspace=0.25,
        )

        self.ax_title = self.ui_figure.add_subplot(self.ui_gs[0:3, 0:30])
        self.ax_toolbar = self.ui_figure.add_subplot(self.ui_gs[4:26, 0:4])
        self.ax_page = self.ui_figure.add_subplot(self.ui_gs[4:26, 5:21])
        self.ax_layout_panel = self.ui_figure.add_subplot(self.ui_gs[4:11, 22:29])
        self.ax_annotation_panel = self.ui_figure.add_subplot(self.ui_gs[11:18, 22:29])
        self.ax_export_panel = self.ui_figure.add_subplot(self.ui_gs[18:26, 22:29])
        self.footer_ax = self.ui_figure.add_subplot(self.ui_gs[27:29, 0:30])

        for ax in [
            self.ax_title,
            self.ax_toolbar,
            self.ax_page,
            self.ax_layout_panel,
            self.ax_annotation_panel,
            self.ax_export_panel,
            self.footer_ax,
        ]:
            ax.set_xticks([])
            ax.set_yticks([])
            ax.axis("off")

        # Page container with subtle border and inner content inset
        self.ax_page.set_facecolor(PAGE_BG_COLOR)
        for spine in self.ax_page.spines.values():
            spine.set_color(THEME["panel_border"])
        self.ax_page.set_frame_on(True)

        self.preview_ax = self.ax_page.inset_axes([0.05, 0.05, 0.90, 0.90])
        self.preview_ax.set_facecolor(PAGE_BG_COLOR)
        self.preview_ax.set_xlim(0, self.spec.layout.width_in)
        self.preview_ax.set_ylim(0, self.spec.layout.height_in)
        self.preview_ax.set_box_aspect(
            max(self.spec.layout.height_in / max(self.spec.layout.width_in, 1e-6), 0.01)
        )
        self.preview_ax.axis("off")

        # Build UI components
        self._build_title()
        self._build_toolbar()
        self._build_controls()
        self._build_footer()

        self.canvas.draw()

    def _build_title(self):
        """Title/header bar."""
        self.ax_title.clear()
        self.ax_title.set_facecolor(THEME["bg_window"])
        self.ax_title.set_xlim(0, 1)
        self.ax_title.set_ylim(0, 1)
        self.ax_title.axis("off")
        self.ax_title.text(
            0.0,
            0.55,
            "Pure Matplotlib Figure Composer",
            fontsize=14,
            weight="bold",
            color=THEME["text_primary"],
            va="center",
        )
        self.ax_title.text(
            0.0,
            0.22,
            "Preview = Export • Spec-driven layout",
            fontsize=10,
            color=THEME["text_secondary"],
            va="center",
        )

    def _build_toolbar(self):
        """Build annotation toolbar."""
        self.ax_toolbar.clear()
        self.ax_toolbar.set_facecolor(THEME["bg_secondary"])
        self.ax_toolbar.set_xlim(0, 1)
        self.ax_toolbar.set_ylim(0, 1)
        self.ax_toolbar.set_frame_on(True)
        for spine in self.ax_toolbar.spines.values():
            spine.set_color(THEME["panel_border"])

        button_height = 0.07
        button_width = 0.86
        start_y = 0.93
        spacing = 0.015

        label_kwargs = {"fontsize": 9, "weight": "bold"}
        button_specs = [
            ("select", "Select", THEME["bg_control"]),
            ("text", "Text", THEME["bg_control"]),
            ("box", "Box", THEME["bg_control"]),
            ("arrow", "Arrow", THEME["bg_control"]),
            ("line", "Line", THEME["bg_control"]),
            ("delete", "Delete", THEME["accent_red"]),
            ("undo", "Undo", THEME["accent_yellow"]),
            ("redo", "Redo", THEME["accent_yellow"]),
            ("export", "Export", THEME["accent_green"]),
        ]

        for idx, (key, label, color) in enumerate(button_specs):
            y_pos = start_y - idx * (button_height + spacing)
            btn_ax = self.ax_toolbar.inset_axes([0.07, y_pos, button_width, button_height])
            btn_ax.set_facecolor(color)
            btn = Button(btn_ax, label, color=color, hovercolor=THEME["bg_secondary"])
            btn.on_clicked(self._make_toolbar_callback(key))
            btn.label.set_fontsize(label_kwargs["fontsize"])
            btn.label.set_weight(label_kwargs["weight"])
            self.toolbar_buttons[key] = btn
            self._toolbar_base_colors[key] = color

        self._update_toolbar_styles(active="select")

    def _build_controls(self):
        """Build stacked control panels on the right."""
        self.control_widgets.clear()

        self._build_layout_section(self.ax_layout_panel)
        self._build_annotation_section(self.ax_annotation_panel)
        self._build_export_section(self.ax_export_panel)
        self.canvas.draw_idle()

    def _update_toolbar_styles(self, active: str | None = None):
        """Visually indicate the active tool."""
        for key, btn in self.toolbar_buttons.items():
            face = self._toolbar_base_colors.get(key, THEME["bg_control"])
            if active and key == active:
                face = THEME["accent_blue"]
            btn.ax.set_facecolor(face)
            btn.hovercolor = THEME["bg_secondary"]
        self.canvas.draw_idle()

    def _style_panel(self, ax):
        """Apply consistent panel styling."""
        ax.clear()
        ax.set_facecolor(THEME["bg_control"])
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_frame_on(True)
        for spine in ax.spines.values():
            spine.set_color(THEME["panel_border"])
        return ax

    def _build_layout_section(self, ax):
        """Layout controls (templates + size)."""
        panel = self._style_panel(ax)

        panel.text(
            0.05,
            0.93,
            "Layout",
            fontsize=11,
            weight="bold",
            color=THEME["text_primary"],
            va="top",
        )

        layout_ax = panel.inset_axes([0.06, 0.47, 0.88, 0.36])
        layout_ax.set_facecolor(THEME["bg_secondary"])
        layout_labels = ("1 panel", "2 horizontal", "2 vertical", "2×2")
        layout_map = {
            (1, 1): 0,
            (1, 2): 1,
            (2, 1): 2,
            (2, 2): 3,
        }
        active_idx = layout_map.get((self.spec.layout.nrows, self.spec.layout.ncols), 0)
        self.layout_selector = RadioButtons(
            layout_ax,
            layout_labels,
            active=active_idx,
        )
        self.layout_selector.on_clicked(self._on_layout_change)
        self.control_widgets["layout_selector"] = self.layout_selector

        panel.text(
            0.06,
            0.40,
            "Size (inches)",
            fontsize=9,
            color=THEME["text_secondary"],
            va="top",
        )

        width_ax = panel.inset_axes([0.15, 0.26, 0.78, 0.1])
        self.width_slider = Slider(
            width_ax,
            "Width",
            2.0,
            12.0,
            valinit=self.spec.layout.width_in,
            valfmt="%.1f",
        )
        self.width_slider.on_changed(self._on_size_change)
        self.control_widgets["width_slider"] = self.width_slider

        height_ax = panel.inset_axes([0.15, 0.12, 0.78, 0.1])
        self.height_slider = Slider(
            height_ax,
            "Height",
            1.0,
            12.0,
            valinit=self.spec.layout.height_in,
            valfmt="%.1f",
        )
        self.height_slider.on_changed(self._on_size_change)
        self.control_widgets["height_slider"] = self.height_slider

    def _build_annotation_section(self, ax):
        """Annotation property editor area."""
        self.annotation_panel = self._style_panel(ax)
        self._refresh_annotation_controls()

    def _refresh_annotation_controls(self):
        """Refresh annotation controls based on selection."""
        panel = getattr(self, "annotation_panel", None)
        if panel is None:
            return

        for key in ("text_box", "fontsize_slider", "lw_slider"):
            self.control_widgets.pop(key, None)

        panel.clear()
        self._style_panel(panel)

        panel.text(
            0.05,
            0.93,
            "Annotation",
            fontsize=11,
            weight="bold",
            color=THEME["text_primary"],
            va="top",
        )

        if self.selected_annotation_id is None:
            panel.text(
                0.5,
                0.55,
                "Select an annotation to edit",
                ha="center",
                va="center",
                fontsize=9,
                color=THEME["text_secondary"],
            )
            self.canvas.draw_idle()
            return

        annot = next(
            (a for a in self.spec.annotations if a.annotation_id == self.selected_annotation_id),
            None,
        )
        if annot is None:
            panel.text(
                0.5,
                0.55,
                "Annotation missing",
                ha="center",
                va="center",
                fontsize=9,
                color=THEME["text_secondary"],
            )
            self.canvas.draw_idle()
            return

        panel.text(
            0.05,
            0.84,
            f"{annot.kind.title()} properties",
            fontsize=10,
            color=THEME["text_secondary"],
            va="top",
        )

        y_pos = 0.72

        if annot.kind == "text":
            text_ax = panel.inset_axes([0.06, y_pos - 0.12, 0.88, 0.12])
            text_box = TextBox(text_ax, "Text", initial=annot.text_content)
            text_box.on_submit(lambda text: self._update_annotation_property("text_content", text))
            self.control_widgets["text_box"] = text_box
            y_pos -= 0.18

            fontsize_ax = panel.inset_axes([0.10, y_pos - 0.10, 0.80, 0.1])
            fontsize_slider = Slider(
                fontsize_ax,
                "Font",
                6,
                24,
                valinit=annot.font_size,
                valfmt="%.0f",
            )
            fontsize_slider.on_changed(
                lambda val: self._update_annotation_property("font_size", float(val))
            )
            self.control_widgets["fontsize_slider"] = fontsize_slider
            y_pos -= 0.16

        lw_ax = panel.inset_axes([0.10, y_pos - 0.10, 0.80, 0.1])
        lw_slider = Slider(
            lw_ax,
            "Line width",
            0.5,
            5.0,
            valinit=annot.linewidth,
            valfmt="%.1f",
        )
        lw_slider.on_changed(lambda val: self._update_annotation_property("linewidth", float(val)))
        self.control_widgets["lw_slider"] = lw_slider
        self.canvas.draw_idle()

    def _build_export_section(self, ax):
        """Export controls."""
        panel = self._style_panel(ax)

        panel.text(
            0.05,
            0.93,
            "Export",
            fontsize=11,
            weight="bold",
            color=THEME["text_primary"],
            va="top",
        )

        format_ax = panel.inset_axes([0.06, 0.52, 0.44, 0.30])
        format_ax.set_facecolor(THEME["bg_secondary"])
        format_selector = RadioButtons(
            format_ax,
            ("PDF", "SVG", "PNG", "TIFF"),
            active=["pdf", "svg", "png", "tiff"].index(self.spec.export.format),
        )
        format_selector.on_clicked(lambda label: self._update_export_property("format", label.lower()))
        self.control_widgets["format_selector"] = format_selector

        dpi_ax = panel.inset_axes([0.60, 0.60, 0.34, 0.1])
        dpi_slider = Slider(
            dpi_ax,
            "DPI",
            72,
            1200,
            valinit=self.spec.export.dpi,
            valfmt="%.0f",
        )
        dpi_slider.on_changed(lambda val: self._update_export_property("dpi", int(val)))
        self.control_widgets["dpi_slider"] = dpi_slider

        panel.text(
            0.06,
            0.44,
            "Presets",
            fontsize=9,
            color=THEME["text_secondary"],
            va="top",
        )

        preset_specs = [
            ("85 mm", 85 / 25.4),
            ("120 mm", 120 / 25.4),
            ("180 mm", 180 / 25.4),
            ("260 mm", 260 / 25.4),
        ]

        y = 0.36
        for label, width_in in preset_specs:
            btn_ax = panel.inset_axes([0.06, y, 0.88, 0.08])
            btn = Button(btn_ax, label, color=THEME["bg_secondary"], hovercolor=THEME["bg_primary"])
            btn.on_clicked(lambda event, w=width_in: self._apply_preset(w))
            self.control_widgets[f"preset_{label}"] = btn
            y -= 0.1

    def _on_layout_change(self, label):
        """Handle layout template change."""
        layouts = {
            "1 panel": (1, 1),
            "2 horizontal": (1, 2),
            "2 vertical": (2, 1),
            "2×2": (2, 2),
        }
        nrows, ncols = layouts[label]

        # Update layout spec
        self.spec.layout.nrows = nrows
        self.spec.layout.ncols = ncols

        # Recreate graph instances for new layout
        instances = []
        graph_ids = list(self.spec.graphs.keys())
        idx = 0

        for row in range(nrows):
            for col in range(ncols):
                # Cycle through available graphs or reuse first graph
                graph_id = graph_ids[idx % len(graph_ids)] if graph_ids else "graph1"
                instances.append(
                    GraphInstance(
                        instance_id=f"inst_{row}_{col}",
                        graph_id=graph_id,
                        row=row,
                        col=col,
                    )
                )
                idx += 1

        self.spec.layout.graph_instances = instances

        # Adjust height for multi-panel layouts
        if nrows > 1:
            self.spec.layout.height_in = self.spec.layout.width_in * 0.5 * nrows

        if "width_slider" in self.control_widgets or "height_slider" in self.control_widgets:
            self._suppress_size_events = True
            if "width_slider" in self.control_widgets:
                self.width_slider.set_val(self.spec.layout.width_in)
            if "height_slider" in self.control_widgets:
                self.height_slider.set_val(self.spec.layout.height_in)
            self._suppress_size_events = False

        self._push_undo()
        self._update_preview()

    def _on_size_change(self, val):
        """Handle size slider change."""
        if self._suppress_size_events:
            return
        self.spec.layout.width_in = self.width_slider.val
        self.spec.layout.height_in = self.height_slider.val
        self._update_preview()
        self._update_footer()

    def _apply_preset(self, width_in):
        """Apply a size preset."""
        aspect = self.spec.layout.height_in / max(self.spec.layout.width_in, 0.1)
        self.spec.layout.width_in = width_in
        self.spec.layout.height_in = width_in * aspect

        # Update sliders if they exist
        if "width_slider" in self.control_widgets or "height_slider" in self.control_widgets:
            self._suppress_size_events = True
            if "width_slider" in self.control_widgets:
                self.width_slider.set_val(width_in)
            if "height_slider" in self.control_widgets:
                self.height_slider.set_val(width_in * aspect)
            self._suppress_size_events = False

        self._push_undo()
        self._update_preview()

    def _update_annotation_property(self, prop, value):
        """Update a property of the selected annotation."""
        if self.selected_annotation_id is None:
            return

        for annot in self.spec.annotations:
            if annot.annotation_id == self.selected_annotation_id:
                setattr(annot, prop, value)
                self._update_preview()
                break

    def _update_export_property(self, prop, value):
        """Update an export spec property."""
        setattr(self.spec.export, prop, value)
        self._update_footer()
        self.canvas.draw_idle()

    def _build_footer(self):
        """Build footer status bar."""
        self.footer_ax.set_facecolor(THEME["bg_secondary"])
        self.footer_ax.set_xlim(0, 1)
        self.footer_ax.set_ylim(0, 1)
        self.footer_ax.axis("off")
        self.footer_text = self.footer_ax.text(
            0.5, 0.5, "",
            ha="center", va="center", fontsize=8.5, family="monospace", color=THEME["text_secondary"]
        )
        self._update_footer()

    def _update_footer(self):
        """Update footer status."""
        w_mm = self.spec.layout.width_in * 25.4
        h_mm = self.spec.layout.height_in * 25.4
        dpi = self.spec.export.dpi
        w_px = int(self.spec.layout.width_in * dpi)
        h_px = int(self.spec.layout.height_in * dpi)
        n_annot = len(self.spec.annotations)

        mode_str = f"Mode: {self.annotation_mode or 'None'}"
        status = (
            f"{mode_str} │ "
            f"Size: {w_mm:.0f}×{h_mm:.0f} mm ({self.spec.layout.width_in:.2f}×{self.spec.layout.height_in:.2f} in) │ "
            f"Export: {w_px}×{h_px} px @ {dpi} dpi │ "
            f"Annotations: {n_annot}"
        )
        self.footer_text.set_text(status)

    def _make_toolbar_callback(self, button_key: str):
        """Create callback for toolbar button."""
        def callback(event):
            if button_key in ("select", "text", "box", "arrow", "line"):
                self.annotation_mode = button_key
                log.info(f"Mode: {button_key}")
                self._update_toolbar_styles(active=button_key)
                self._update_footer()
                self.canvas.draw_idle()
            elif button_key == "delete":
                self._delete_selected_annotation()
            elif button_key == "undo":
                self._undo()
            elif button_key == "redo":
                self._redo()
            elif button_key == "export":
                self.export_figure()
        return callback

    def _connect_events(self):
        """Connect Matplotlib events."""
        self.canvas.mpl_connect("button_press_event", self._on_mouse_press)
        self.canvas.mpl_connect("button_release_event", self._on_mouse_release)
        self.canvas.mpl_connect("motion_notify_event", self._on_mouse_motion)
        self.canvas.mpl_connect("key_press_event", self._on_key_press)

    def _event_in_preview(self, event) -> bool:
        """Return True if event occurred inside the preview/page bbox."""
        bbox = self.preview_ax.get_window_extent()
        return bbox.contains(event.x, event.y)

    def _event_to_page_fraction(self, event) -> tuple[float, float]:
        """Convert an event position to page-relative 0-1 coordinates."""
        inv = self.preview_ax.transData.inverted()
        x_page, y_page = inv.transform((event.x, event.y))
        width = max(self.preview_ax.get_xlim()[1] - self.preview_ax.get_xlim()[0], 1e-6)
        height = max(self.preview_ax.get_ylim()[1] - self.preview_ax.get_ylim()[0], 1e-6)
        return x_page / width, y_page / height

    def _on_mouse_press(self, event):
        """Handle mouse press for annotation creation/selection."""
        if not self._event_in_preview(event):
            return

        x_norm, y_norm = self._event_to_page_fraction(event)

        if self.annotation_mode == "select":
            # TODO: Implement selection by checking proximity to annotations
            self.selected_annotation_id = None
            self._refresh_annotation_controls()
        elif self.annotation_mode == "text":
            # Create text annotation at click point
            annot = AnnotationSpec(
                annotation_id=str(uuid.uuid4()),
                kind="text",
                target_type="figure",
                coord_system="axes",
                x0=x_norm,
                y0=y_norm,
                text_content="Text",
                font_size=12.0,
            )
            self.spec.annotations.append(annot)
            self.selected_annotation_id = annot.annotation_id
            self._push_undo()
            self._update_preview()
            self._refresh_annotation_controls()
        elif self.annotation_mode in ("box", "arrow", "line"):
            # Start creating box/arrow/line
            self._drag_start = (x_norm, y_norm)
            self._creating_annotation = AnnotationSpec(
                annotation_id=str(uuid.uuid4()),
                kind=self.annotation_mode,
                target_type="figure",
                coord_system="axes",
                x0=x_norm,
                y0=y_norm,
                x1=x_norm,
                y1=y_norm,
            )

    def _on_mouse_release(self, event):
        """Handle mouse release to finalize annotation creation."""
        if self._creating_annotation is not None:
            # Finalize the annotation
            self.spec.annotations.append(self._creating_annotation)
            self.selected_annotation_id = self._creating_annotation.annotation_id
            self._creating_annotation = None
            self._drag_start = None
            self._push_undo()
            self._update_preview()
            self._refresh_annotation_controls()

    def _on_mouse_motion(self, event):
        """Handle mouse motion for drag operations."""
        if not self._event_in_preview(event):
            return

        if self._creating_annotation is not None and self._drag_start is not None:
            # Update end point of creating annotation
            x_norm, y_norm = self._event_to_page_fraction(event)
            self._creating_annotation.x1 = x_norm
            self._creating_annotation.y1 = y_norm
            # Show preview (would need temp render)

    def _on_key_press(self, event):
        """Handle keyboard shortcuts."""
        if event.key == "delete":
            self._delete_selected_annotation()
        elif event.key == "ctrl+z":
            self._undo()
        elif event.key == "ctrl+y" or event.key == "ctrl+shift+z":
            self._redo()

    def _update_preview(self):
        """Re-render preview from spec."""
        try:
            # Remove previously created graph axes from prior renders
            for ax in self._preview_axes_map.values():
                try:
                    ax.remove()
                except ValueError:
                    pass
            self._preview_axes_map = {}

            self.preview_ax.set_facecolor(PAGE_BG_COLOR)
            self.preview_ax.set_xlim(0, self.spec.layout.width_in)
            self.preview_ax.set_ylim(0, self.spec.layout.height_in)
            self.ax_page.set_box_aspect(
                max(self.spec.layout.height_in / max(self.spec.layout.width_in, 1e-6), 0.01)
            )
            self.preview_ax.set_box_aspect(
                max(self.spec.layout.height_in / max(self.spec.layout.width_in, 1e-6), 0.01)
            )
            for spine in self.preview_ax.spines.values():
                spine.set_visible(False)
            self.preview_ax.set_xticks([])
            self.preview_ax.set_yticks([])
            self.preview_ax.tick_params(left=False, labelleft=False, bottom=False, labelbottom=False)
            self.preview_ax.set_frame_on(False)

            if self.trace_model is None:
                self.preview_ax.text(
                    0.5,
                    0.5,
                    "No trace model loaded",
                    ha="center",
                    va="center",
                    fontsize=12,
                    color="#999999",
                )
                self._update_footer()
                self.canvas.draw_idle()
                return

            def trace_provider(sample_id: str):
                return self.trace_model

            self._preview_axes_map = render_into_axes(
                self.preview_ax,
                self.spec,
                trace_provider,
                event_times=self.event_times,
                event_labels=self.event_labels,
                event_colors=self.event_colors,
            )

            self._update_footer()
            self.canvas.draw_idle()

        except Exception as e:
            log.error(f"Preview error: {e}", exc_info=True)
            self.preview_ax.text(
                0.5, 0.5, f"Error:\n{str(e)[:100]}",
                ha="center", va="center", fontsize=10, color="#cc0000"
            )
            self.canvas.draw_idle()

    def _delete_selected_annotation(self):
        """Delete selected annotation."""
        if self.selected_annotation_id is None:
            return

        self.spec.annotations = [
            a for a in self.spec.annotations
            if a.annotation_id != self.selected_annotation_id
        ]
        self.selected_annotation_id = None
        self._push_undo()
        self._update_preview()
        self._refresh_annotation_controls()

    def _push_undo(self):
        """Push current spec to undo stack."""
        spec_copy = copy.deepcopy(self.spec)
        self._undo_stack.append(spec_copy)
        if len(self._undo_stack) > self._max_undo:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def _undo(self):
        """Undo last action."""
        if len(self._undo_stack) < 2:
            return

        current = self._undo_stack.pop()
        self._redo_stack.append(current)
        self.spec = copy.deepcopy(self._undo_stack[-1])
        self._update_preview()
        self._refresh_annotation_controls()

    def _redo(self):
        """Redo last undone action."""
        if not self._redo_stack:
            return

        self.spec = copy.deepcopy(self._redo_stack.pop())
        self._undo_stack.append(copy.deepcopy(self.spec))
        self._update_preview()
        self._refresh_annotation_controls()

    def export_figure(self):
        """Export figure at target DPI."""
        format_filters = {
            "pdf": "PDF (*.pdf)",
            "svg": "SVG (*.svg)",
            "png": "PNG (*.png)",
            "tiff": "TIFF (*.tiff *.tif)",
        }

        current_format = self.spec.export.format
        filter_str = ";;".join(format_filters.values())
        initial_filter = format_filters.get(current_format, format_filters["pdf"])

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Figure",
            f"figure.{current_format}",
            filter_str,
            initial_filter,
        )

        if not file_path:
            return

        try:
            def trace_provider(sample_id: str):
                return self.trace_model

            export_fig = render_figure(
                self.spec,
                trace_provider,
                dpi=self.spec.export.dpi,
                event_times=self.event_times,
                event_labels=self.event_labels,
                event_colors=self.event_colors,
            )

            export_fig.savefig(
                file_path,
                format=self.spec.export.format,
                dpi=self.spec.export.dpi if self.spec.export.format in ("png", "tiff") else None,
                bbox_inches="tight",
                transparent=self.spec.export.transparent,
            )

            plt.close(export_fig)

            QMessageBox.information(
                self,
                "Export Complete",
                f"Figure exported to:\n{file_path}",
            )
            log.info(f"Exported: {file_path}")

        except Exception as e:
            log.error(f"Export failed: {e}", exc_info=True)
            QMessageBox.critical(
                self,
                "Export Failed",
                f"Failed to export:\n{str(e)}",
            )
