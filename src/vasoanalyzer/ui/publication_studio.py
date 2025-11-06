"""Figure Composer - Advanced figure styling and export workspace."""

from __future__ import annotations

import contextlib
from collections.abc import Mapping, Sequence
from typing import Any, cast

from PyQt5.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt5.QtGui import (
    QBrush,
    QCloseEvent,
    QColor,
    QIcon,
    QKeySequence,
    QPainter,
    QPen,
)
from PyQt5.QtWidgets import (
    QAction,
    QComboBox,
    QDialog,
    # QDockWidget,  # Removed - no longer using dock system
    QGraphicsDropShadowEffect,
    QGraphicsProxyWidget,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QToolBar,
    QUndoCommand,
    QUndoStack,
    QVBoxLayout,
    QWidget,
)

from vasoanalyzer.core.trace_model import TraceModel
from vasoanalyzer.ui.builtin_presets import get_builtin_presets
from vasoanalyzer.ui.constants import DEFAULT_STYLE
from vasoanalyzer.ui.dialogs.unified_settings_dialog import UnifiedPlotSettingsDialog

# NOTE: Old dock system imports removed - using fixed three-panel layout
# from vasoanalyzer.ui.docks.advanced_style_dock import AdvancedStyleDock
# from vasoanalyzer.ui.docks.export_queue_dock import ExportQueueDock, ExportStatus
# from vasoanalyzer.ui.docks.layout_dock import LayoutDock
# from vasoanalyzer.ui.docks.preset_library_dock import PresetLibraryDock
from vasoanalyzer.ui.plots.channel_track import ChannelTrackSpec
from vasoanalyzer.ui.plots.plot_host import LayoutState, PlotHost
from vasoanalyzer.ui.publication import (
    Epoch,
    EpochEditorDialog,
    EpochLayer,
    EpochTheme,
    events_to_epochs,
)
from vasoanalyzer.ui.style_manager import PlotStyleManager
from vasoanalyzer.ui.theme import CURRENT_THEME
from vasoanalyzer.ui.widgets import CustomToolbar

__all__ = ["PublicationStudioWindow"]


class StyleChangeCommand(QUndoCommand):
    """Undo command for style changes."""

    def __init__(
        self,
        studio: PublicationStudioWindow,
        old_style: dict[str, Any],
        new_style: dict[str, Any],
        description: str = "Change Style",
    ) -> None:
        super().__init__(description)
        self.studio = studio
        self.old_style = old_style.copy()
        self.new_style = new_style.copy()

    def redo(self) -> None:
        """Apply new style."""
        if self.studio._style_manager:
            self.studio._style_manager.replace(self.new_style)
            self.studio._current_preset_name = None  # Custom style, no preset
            self.studio._apply_style_to_plot()
            self.studio._sync_canvas_size_to_figure()
            self.studio.plot_host.canvas.draw_idle()

    def undo(self) -> None:
        """Revert to old style."""
        if self.studio._style_manager:
            self.studio._style_manager.replace(self.old_style)
            self.studio._current_preset_name = None  # Custom style, no preset
            self.studio._apply_style_to_plot()
            self.studio._sync_canvas_size_to_figure()
            self.studio.plot_host.canvas.draw_idle()


class CanvasView(QGraphicsView):
    """Graphics view for the canvas with zoom and pan support."""

    zoomChanged = pyqtSignal(float)  # Emits zoom level (1.0 = 100%)

    def __init__(self, scene: QGraphicsScene, parent: QWidget | None = None) -> None:
        super().__init__(scene, parent)
        self.setRenderHints(
            QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform
        )
        self.setBackgroundBrush(QBrush(QColor(243, 244, 246)))  # Light grey #F3F4F6
        self.setDragMode(QGraphicsView.NoDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setFocusPolicy(Qt.StrongFocus)  # Enable keyboard events

        self._zoom_level: float = 1.0
        self._is_panning: bool = False
        self._pan_start_pos: QPointF = QPointF()
        self._space_pressed: bool = False

    def wheelEvent(self, event) -> None:
        """Handle mouse wheel for zooming."""
        # Check for Ctrl/Cmd modifier for zoom
        if event.modifiers() & (Qt.ControlModifier | Qt.MetaModifier):
            angle = event.angleDelta().y()
            factor = 1.0015**angle
            new_zoom = max(0.1, min(8.0, self._zoom_level * factor))

            # Apply scaling
            scale_factor = new_zoom / self._zoom_level
            self.scale(scale_factor, scale_factor)

            self._zoom_level = new_zoom
            self.zoomChanged.emit(self._zoom_level)
        else:
            # Normal scroll behavior
            super().wheelEvent(event)

    def keyPressEvent(self, event) -> None:
        """Handle key press events."""
        if event.key() == Qt.Key_Space:
            self._space_pressed = True
            event.accept()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:
        """Handle key release events."""
        if event.key() == Qt.Key_Space:
            self._space_pressed = False
            if self._is_panning:
                self._is_panning = False
                self.setCursor(Qt.ArrowCursor)
            event.accept()
        else:
            super().keyReleaseEvent(event)

    def mousePressEvent(self, event) -> None:
        """Handle mouse press for panning."""
        if event.button() == Qt.MiddleButton or (
            event.button() == Qt.LeftButton and self._space_pressed
        ):
            self._is_panning = True
            self._pan_start_pos = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        """Handle mouse move for panning."""
        if self._is_panning:
            delta = event.pos() - self._pan_start_pos
            self._pan_start_pos = event.pos()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        """Handle mouse release to end panning."""
        if event.button() == Qt.MiddleButton or (
            event.button() == Qt.LeftButton and self._is_panning
        ):
            self._is_panning = False
            self.setCursor(Qt.ArrowCursor)
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def fit_in_view(self, rect: QRectF) -> None:
        """Fit the given rectangle in the view."""
        self.fitInView(rect, Qt.KeepAspectRatio)
        # Update zoom level based on the transform
        self._zoom_level = self.transform().m11()
        self.zoomChanged.emit(self._zoom_level)

    def zoom_to_level(self, level: float) -> None:
        """Zoom to a specific level (1.0 = 100%)."""
        scale_factor = level / self._zoom_level
        self.scale(scale_factor, scale_factor)
        self._zoom_level = level
        self.zoomChanged.emit(self._zoom_level)


class PublicationStudioWindow(QMainWindow):
    """
    Dedicated workspace for creating publication-ready figures.

    Provides:
    - Live preview with embedded PlotHost
    - Advanced styling controls (dockable panels)
    - Style preset library management
    - Batch export queue
    - Undo/redo for styling operations
    """

    # Signal emitted when preset is saved (for main window sync)
    preset_saved = pyqtSignal(dict)

    # Signal emitted when window closes
    studio_closed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Figure Composer")
        self.setObjectName("FigureComposerWindow")

        # Core state
        self._trace_model: TraceModel | None = None
        self._event_times: list[float] = []
        self._event_colors: list[str] | None = None
        self._event_labels: list[str] = []
        self._event_label_meta: list[dict[str, Any]] = []
        self._channel_specs: list[ChannelTrackSpec] = []
        self._layout_state: LayoutState | None = None

        # Epoch overlay state
        self._epochs: list[Epoch] = []
        self._epoch_layer: EpochLayer | None = None
        self._epoch_theme: EpochTheme = EpochTheme()
        self._epochs_visible: bool = True

        # Style management
        self._style_manager: PlotStyleManager | None = None
        self._current_preset_name: str | None = None
        self.grid_visible: bool = True
        self._event_highlight_color: str = DEFAULT_STYLE.get("event_highlight_color", "#1D5CFF")
        self._event_highlight_alpha: float = float(DEFAULT_STYLE.get("event_highlight_alpha", 0.95))
        self._event_highlight_duration_ms: int = int(
            DEFAULT_STYLE.get("event_highlight_duration_ms", 2000)
        )

        # Undo/redo stack for styling operations
        self.undo_stack = QUndoStack(self)

        # Canvas and zoom state
        self._canvas_width_in: float = 10.0  # inches (PowerPoint standard)
        self._canvas_height_in: float = 7.5  # inches
        self._canvas_dpi: int = 120
        self._zoom_level: float = 1.0  # 1.0 = 100%
        self._zoom_levels = [0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0]

        # Load built-in presets
        self._builtin_presets = get_builtin_presets()

        # Build UI
        self._build_ui()
        self._create_menus()
        # NOTE: Old dock system removed in favor of fixed three-panel layout
        # self._create_dock_areas()

        # Apply theme
        self._apply_theme()

        # Restore window geometry
        self.resize(1400, 900)

    # ------------------------------------------------------------------ Public API

    def icon_path(self, filename: str) -> str:
        """Return absolute path to an icon shipped with the application."""
        from utils import resource_path

        return str(resource_path("icons", filename))

    def load_from_main_window(
        self,
        trace_model: TraceModel | None,
        event_times: list[float],
        event_colors: list[str] | None,
        event_labels: list[str],
        event_label_meta: list[dict[str, Any]],
        channel_specs: list[ChannelTrackSpec],
        layout_state: LayoutState | None,
        style_dict: dict[str, Any] | None = None,
    ) -> None:
        """
        Clone the current plot state from main window.

        Args:
            trace_model: The trace data model
            event_times: Event time markers
            event_colors: Event marker colors
            event_labels: Event text labels
            event_label_meta: Event metadata (priority, category, etc.)
            channel_specs: Channel track specifications
            layout_state: Channel layout configuration
            style_dict: Optional initial style to apply
        """
        self._trace_model = trace_model
        self._event_times = event_times.copy()
        self._event_colors = event_colors.copy() if event_colors else None
        self._event_labels = event_labels.copy()
        self._event_label_meta = [meta.copy() for meta in event_label_meta]
        self._channel_specs = [
            ChannelTrackSpec(
                track_id=spec.track_id,
                label=spec.label,
                component=spec.component,
                height_ratio=spec.height_ratio,
            )
            for spec in channel_specs
        ]
        self._layout_state = layout_state

        # Initialize style manager
        if style_dict:
            self._style_manager = PlotStyleManager(style_dict)

        # Populate plot host
        self._populate_plot_host()

        # Clear undo stack (fresh start)
        self.undo_stack.clear()

    # ------------------------------------------------------------------ Exposed Event State

    @property
    def event_labels(self) -> list[str]:
        """Expose current event labels for dialogs."""
        return list(self._event_labels)

    @property
    def event_times(self) -> list[float]:
        """Expose current event timestamps for dialogs."""
        return list(self._event_times)

    @property
    def event_label_meta(self) -> list[dict[str, Any]]:
        """Expose current event metadata for dialogs."""
        return [meta.copy() for meta in self._event_label_meta]

    @property
    def event_text_objects(self) -> list[tuple[Any, float, str]]:
        """Expose event annotation text artists for styling."""
        if not hasattr(self, "plot_host") or self.plot_host is None:
            return []
        objects = self.plot_host.annotation_text_objects()
        return list(cast(Sequence[tuple[Any, float, str]], objects))

    def get_current_style(self) -> dict[str, Any]:
        """Snapshot current plot style from PlotHost artists."""
        if self._style_manager:
            return cast(dict[str, Any], self._style_manager.style())
        return self._snapshot_style()

    def set_epochs(self, epochs: list[Epoch]) -> None:
        """Set epochs for protocol timeline overlay."""
        self._epochs = epochs
        if self._epoch_layer is not None:
            self._epoch_layer.set_epochs(epochs)
            self.plot_host.canvas.draw_idle()

    def get_epochs(self) -> list[Epoch]:
        """Get current epochs."""
        return self._epochs.copy()

    def auto_generate_epochs(self) -> None:
        """Auto-generate epochs from event data."""
        if not self._event_times:
            return

        # Convert events to epochs
        epochs = events_to_epochs(
            self._event_times,
            self._event_labels,
            self._event_label_meta,
            default_duration=60.0,
            merge_consecutive=True,
        )

        self.set_epochs(epochs)

    def toggle_epochs_visibility(self, visible: bool) -> None:
        """Toggle epoch overlay visibility."""
        self._epochs_visible = visible
        if self._epoch_layer is not None:
            if visible:
                self._epoch_layer.attach(self._get_primary_axes())
            else:
                self._epoch_layer.attach(None)
            self.plot_host.canvas.draw_idle()

    def _get_primary_axes(self) -> Any:
        """Get the primary (top) axes for epoch overlay."""
        if not self.plot_host._tracks:
            return None
        # Get first visible track's axes
        for track in self.plot_host._tracks.values():
            if hasattr(track, "ax") and track.ax is not None:
                return track.ax
        return None

    def _x_axis_for_style(self):
        """Return the shared X axis used for applying style updates."""
        if not hasattr(self, "plot_host") or self.plot_host is None:
            return None
        axis = self.plot_host.bottom_axis()
        if axis is None:
            axis = self._get_primary_axes()
        return axis

    def _set_shared_xlabel(self, text: str) -> None:
        """Update the shared X label across all stacked axes."""
        if not hasattr(self, "plot_host") or self.plot_host is None:
            return
        self.plot_host.set_shared_xlabel(text)

    def apply_event_label_overrides(
        self,
        labels: Sequence[str],
        metadata: Sequence[Mapping[str, Any]],
    ) -> None:
        """Apply label overrides coming from the unified settings dialog."""
        if labels is None or metadata is None or not hasattr(self, "plot_host"):
            return

        new_labels = list(labels)
        if not new_labels:
            self._event_labels = []
            self._event_label_meta = []
            self.plot_host.set_events(
                self._event_times,
                self._event_colors,
                [],
                [],
            )
            self.plot_host.canvas.draw_idle()
            return

        if len(new_labels) != len(self._event_labels):
            return

        new_meta = [dict(entry or {}) for entry in metadata]
        if len(new_meta) < len(new_labels):
            new_meta.extend({} for _ in range(len(new_labels) - len(new_meta)))
        elif len(new_meta) > len(new_labels):
            new_meta = new_meta[: len(new_labels)]

        self._event_labels = new_labels
        self._event_label_meta = new_meta

        self.plot_host.set_events(
            self._event_times,
            self._event_colors,
            self._event_labels,
            self._event_label_meta,
        )
        self.plot_host.canvas.draw_idle()

    def apply_preset(self, preset: dict[str, Any], with_undo: bool = True) -> None:
        """
        Apply a style preset to the current figure.

        Args:
            preset: Preset dictionary (must contain "style" key)
            with_undo: Whether to add to undo stack (default True)
        """
        if not self._style_manager:
            self._style_manager = PlotStyleManager()

        if with_undo:
            # Create undo command for preset application
            old_style = self._style_manager.style()
            preset_style = preset.get("style", {})
            preset_name = preset.get("name", "Unknown")
            command = StyleChangeCommand(
                self, old_style, preset_style, f"Apply Preset: {preset_name}"
            )
            self.undo_stack.push(command)
        else:
            # Direct application without undo
            self._style_manager.from_preset(preset)
            self._apply_style_to_plot()
            self._sync_canvas_size_to_figure()
            self._current_preset_name = preset.get("name")

    def save_current_as_preset(
        self, name: str, description: str = "", tags: list[str] | None = None
    ) -> dict[str, Any]:
        """
        Save current style as a named preset.

        Args:
            name: Preset name
            description: Optional description
            tags: Optional tags (e.g., ["journal", "nature"])

        Returns:
            Preset dictionary with metadata
        """
        if not self._style_manager:
            return {}

        # Use PlotStyleManager's to_preset method
        preset = cast(dict[str, Any], self._style_manager.to_preset(name, description, tags))
        self._current_preset_name = name
        self.preset_saved.emit(preset)
        return preset

    # ------------------------------------------------------------------ UI Construction

    def _build_ui(self) -> None:
        """Build UI with QGraphicsView-based canvas."""
        # Create main splitter (3-way: left | center | right)
        main_splitter = QSplitter(Qt.Horizontal, self)

        # ===================================================================
        # LEFT PANEL: Inspector tabs (Settings)
        # ===================================================================
        self.left_panel = QWidget()
        left_layout = QVBoxLayout(self.left_panel)
        left_layout.setContentsMargins(4, 4, 4, 4)
        left_layout.setSpacing(4)

        # Create tabbed widget for settings
        self.settings_tabs = QTabWidget()
        self.settings_tabs.setDocumentMode(True)

        # Add placeholder tabs (will be properly populated later)
        self.settings_tabs.addTab(QWidget(), "Canvas & Frame")
        self.settings_tabs.addTab(QWidget(), "Layout")
        self.settings_tabs.addTab(QWidget(), "Axes")
        self.settings_tabs.addTab(QWidget(), "Style")
        self.settings_tabs.addTab(QWidget(), "Events")

        left_layout.addWidget(self.settings_tabs)
        self.left_panel.setMinimumWidth(280)
        self.left_panel.setMaximumWidth(400)

        # ===================================================================
        # CENTER PANEL: Graphics scene with canvas
        # ===================================================================
        # Create scene and view
        self.canvas_scene = QGraphicsScene(self)
        self.canvas_view = CanvasView(self.canvas_scene, self)

        # Connect zoom signal
        self.canvas_view.zoomChanged.connect(self._on_view_zoom_changed)

        # Create white canvas item with drop shadow
        canvas_width_px = self._canvas_width_in * self._canvas_dpi
        canvas_height_px = self._canvas_height_in * self._canvas_dpi

        self.canvas_item = QGraphicsRectItem(0, 0, canvas_width_px, canvas_height_px)
        self.canvas_item.setBrush(QBrush(QColor(255, 255, 255)))  # White
        self.canvas_item.setPen(QPen(Qt.NoPen))

        # Add drop shadow effect
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(30)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 60))
        self.canvas_item.setGraphicsEffect(shadow)

        self.canvas_scene.addItem(self.canvas_item)

        # Create PlotHost and embed in scene
        self.plot_host = PlotHost(dpi=self._canvas_dpi)
        self.plot_host.canvas.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        # Set plot host size to match canvas
        plot_width_px = int(canvas_width_px)
        plot_height_px = int(canvas_height_px)
        self.plot_host.canvas.setFixedSize(plot_width_px, plot_height_px)
        self.plot_host.figure.set_size_inches(self._canvas_width_in, self._canvas_height_in)

        # Create proxy widget to embed matplotlib canvas in scene
        self.plot_proxy = QGraphicsProxyWidget(self.canvas_item)
        self.plot_proxy.setWidget(self.plot_host.canvas)
        self.plot_proxy.setPos(0, 0)

        # Set scene rect with padding around canvas
        padding = 200
        self.canvas_scene.setSceneRect(
            -padding, -padding, canvas_width_px + 2 * padding, canvas_height_px + 2 * padding
        )

        # ===================================================================
        # RIGHT PANEL: Export queue
        # ===================================================================
        self.right_panel = QWidget()
        right_layout = QVBoxLayout(self.right_panel)
        right_layout.setContentsMargins(4, 4, 4, 4)

        # Export queue (placeholder)
        export_label = QLabel("Export Queue")
        export_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        right_layout.addWidget(export_label)
        right_layout.addStretch()

        self.right_panel.setMinimumWidth(250)
        self.right_panel.setMaximumWidth(350)

        # ===================================================================
        # Add panels to splitter
        # ===================================================================
        main_splitter.addWidget(self.left_panel)
        main_splitter.addWidget(self.canvas_view)
        main_splitter.addWidget(self.right_panel)

        # Set initial splitter sizes (left:center:right = 1:3:1)
        main_splitter.setSizes([300, 900, 300])
        main_splitter.setStretchFactor(0, 0)  # Left doesn't stretch
        main_splitter.setStretchFactor(1, 1)  # Center stretches
        main_splitter.setStretchFactor(2, 0)  # Right doesn't stretch

        self.setCentralWidget(main_splitter)

        # Create toolbar and status bar
        self._create_tools_toolbar()
        self._create_plot_toolbar()
        self._create_status_bar()

        # Fit canvas in view initially
        self.canvas_view.fit_in_view(self.canvas_item.rect())

        # Populate preset combo with built-in presets
        self._populate_preset_combo()

    def _populate_preset_combo(self) -> None:
        """Populate the preset combo box with built-in presets."""
        if not hasattr(self, "preset_combo"):
            return

        self.preset_combo.blockSignals(True)
        # Clear existing items except the first "(Select Preset)" item
        while self.preset_combo.count() > 1:
            self.preset_combo.removeItem(1)

        # Add built-in presets
        for preset in self._builtin_presets:
            preset_name = preset.get("name", "Unnamed")
            self.preset_combo.addItem(preset_name)

        self.preset_combo.blockSignals(False)

    def _sync_canvas_size_to_figure(self) -> None:
        """Update status bar with current figure info."""
        if hasattr(self, "_update_status_bar"):
            self._update_status_bar()

    def _apply_canvas_size(self) -> None:
        """Apply current canvas size to canvas item and figure."""
        if not hasattr(self, "plot_host") or not hasattr(self, "canvas_item"):
            return

        # Calculate new canvas size in pixels
        canvas_width_px = self._canvas_width_in * self._canvas_dpi
        canvas_height_px = self._canvas_height_in * self._canvas_dpi

        # Update canvas item rectangle
        self.canvas_item.setRect(0, 0, canvas_width_px, canvas_height_px)

        # Update figure size
        self.plot_host.figure.set_size_inches(self._canvas_width_in, self._canvas_height_in)

        # Update plot host canvas size
        self.plot_host.canvas.setFixedSize(int(canvas_width_px), int(canvas_height_px))

        # Update scene rect with padding
        padding = 200
        self.canvas_scene.setSceneRect(
            -padding, -padding, canvas_width_px + 2 * padding, canvas_height_px + 2 * padding
        )

        # Redraw
        self.plot_host.canvas.draw_idle()

        # Fit canvas in view
        if hasattr(self, "canvas_view"):
            self.canvas_view.fit_in_view(self.canvas_item.rect())

        # Update status bar
        self._sync_canvas_size_to_figure()

    def _on_view_zoom_changed(self, zoom_level: float) -> None:
        """Handle zoom level change from CanvasView."""
        self._zoom_level = zoom_level

        # Update zoom combo if we have one
        if hasattr(self, "zoom_combo"):
            self.zoom_combo.blockSignals(True)
            # Find closest zoom level or set custom
            zoom_pct = int(zoom_level * 100)
            idx = self.zoom_combo.findText(f"{zoom_pct}%")
            if idx >= 0:
                self.zoom_combo.setCurrentIndex(idx)
            else:
                self.zoom_combo.setCurrentText(f"{zoom_pct}%")
            self.zoom_combo.blockSignals(False)

        # Update status bar
        self._sync_canvas_size_to_figure()

    def _create_tools_toolbar(self) -> None:
        """Create toolbar with canvas size, presets, and zoom controls."""
        toolbar = QToolBar("Figure Tools", self)
        toolbar.setObjectName("FigureToolsToolbar")
        self.addToolBar(Qt.TopToolBarArea, toolbar)

        # === Canvas Size Preset ===
        toolbar.addWidget(QLabel("Canvas:"))
        self.canvas_size_combo = QComboBox()
        self.canvas_size_combo.setMinimumWidth(160)
        self.canvas_size_combo.addItem("PowerPoint (10×7.5 in)", (10.0, 7.5))
        self.canvas_size_combo.addItem("Nature Single (3.5×3 in)", (3.5, 3.0))
        self.canvas_size_combo.addItem("Nature Double (7×5 in)", (7.0, 5.0))
        self.canvas_size_combo.addItem("Science (8×6 in)", (8.0, 6.0))
        self.canvas_size_combo.addItem("Letter (8.5×11 in)", (8.5, 11.0))
        self.canvas_size_combo.addItem("A4 (8.3×11.7 in)", (8.3, 11.7))
        self.canvas_size_combo.setCurrentIndex(0)  # PowerPoint default
        self.canvas_size_combo.currentIndexChanged.connect(self._on_canvas_size_changed)
        toolbar.addWidget(self.canvas_size_combo)

        toolbar.addSeparator()

        # === Style Presets ===
        toolbar.addWidget(QLabel("Preset:"))
        self.preset_combo = QComboBox()
        self.preset_combo.setMinimumWidth(150)
        self.preset_combo.addItem("(Select Preset)")
        # Will be populated when presets are loaded
        self.preset_combo.currentIndexChanged.connect(self._on_preset_combo_changed)
        toolbar.addWidget(self.preset_combo)

        toolbar.addSeparator()

        # === Zoom Controls ===
        toolbar.addWidget(QLabel("Zoom:"))

        # Zoom out button
        zoom_out_btn = QAction("−", self)
        zoom_out_btn.setToolTip("Zoom Out")
        zoom_out_btn.triggered.connect(self._on_zoom_out)
        toolbar.addAction(zoom_out_btn)

        # Zoom combo
        self.zoom_combo = QComboBox()
        self.zoom_combo.setMinimumWidth(80)
        for zoom in self._zoom_levels:
            self.zoom_combo.addItem(f"{int(zoom * 100)}%", zoom)
        self.zoom_combo.addItem("Fit", "fit")
        self.zoom_combo.setCurrentText("100%")
        self.zoom_combo.currentIndexChanged.connect(self._on_zoom_changed)
        toolbar.addWidget(self.zoom_combo)

        # Zoom in button
        zoom_in_btn = QAction("+", self)
        zoom_in_btn.setToolTip("Zoom In")
        zoom_in_btn.triggered.connect(self._on_zoom_in)
        toolbar.addAction(zoom_in_btn)

        toolbar.addSeparator()

        # === View Controls ===
        reset_action = QAction("Reset View", self)
        reset_action.setToolTip("Reset to full data range (Ctrl+R)")
        reset_action.setShortcut("Ctrl+R")
        reset_action.triggered.connect(self._on_reset_view)
        toolbar.addAction(reset_action)

        fit_action = QAction("Auto Fit", self)
        fit_action.setToolTip("Auto-fit axes to data (Ctrl+F)")
        fit_action.setShortcut("Ctrl+F")
        fit_action.triggered.connect(self._on_fit_data)
        toolbar.addAction(fit_action)

    def _create_plot_toolbar(self) -> None:
        """Create custom matplotlib navigation toolbar for plot interactions."""
        # Create custom toolbar with styled icons
        toolbar = CustomToolbar(self.plot_host.canvas, self, reset_callback=self._on_reset_view)
        toolbar.setObjectName("PlotNavigationToolbar")
        toolbar.setIconSize(QSize(22, 22))
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        toolbar.setFloatable(False)
        toolbar.setMovable(False)
        toolbar.setStyleSheet(
            f"""
            QToolBar {{
                background: transparent;
                border: none;
                padding: 0px;
                spacing: 0px;
            }}
            QToolBar > QToolButton {{
                background: transparent;
                border: none;
                border-radius: 8px;
                margin: 0px 5px;
                padding: 6px 8px;
                color: {CURRENT_THEME["text"]};
            }}
            QToolBar > QToolButton:hover {{
                background: {CURRENT_THEME["button_hover_bg"]};
            }}
            QToolBar > QToolButton:checked {{
                background: {CURRENT_THEME["button_active_bg"]};
            }}
        """
        )

        # Remove coordinate display
        if hasattr(toolbar, "coordinates"):
            toolbar.coordinates = lambda *args, **kwargs: None
            for act in list(toolbar.actions()):
                if isinstance(act, QAction) and act.text() == "":
                    toolbar.removeAction(act)

        # Get base matplotlib actions
        base_actions = getattr(toolbar, "_actions", {})
        home_act = base_actions.get("home")
        back_act = base_actions.get("back")
        forward_act = base_actions.get("forward")
        pan_act = base_actions.get("pan")
        zoom_act = base_actions.get("zoom")
        subplots_act = base_actions.get("subplots")
        save_act = base_actions.get("save")

        # Remove all default actions
        for action in list(toolbar.actions()):
            toolbar.removeAction(action)

        # Customize actions with icons and tooltips
        if home_act:
            home_act.setText("Reset view")
            home_act.setShortcut(QKeySequence("R"))
            home_act.setToolTip(
                "<b>Reset View</b> <kbd>R</kbd><br><br>"
                "Resets plot to show entire trace.<br>"
                "Use to return to full time range."
            )
            home_act.setStatusTip("Reset the plot to the full time range.")
            home_act.setIcon(QIcon(self.icon_path("Home.svg")))

        if back_act:
            back_act.setText("Back")
            back_act.setToolTip(
                "<b>Back</b><br><br>"
                "Return to previous view in history.<br>"
                "Navigate backward through zoom history."
            )
            back_act.setIcon(QIcon(self.icon_path("Back.svg")))

        if forward_act:
            forward_act.setText("Forward")
            forward_act.setToolTip(
                "<b>Forward</b><br><br>"
                "Go to next view in history.<br>"
                "Navigate forward through zoom history."
            )
            forward_act.setIcon(QIcon(self.icon_path("Forward.svg")))

        if pan_act:
            pan_act.setText("Pan")
            pan_act.setToolTip(
                "<b>Pan</b> <kbd>P</kbd><br><br>"
                "Click and drag to move the view.<br>"
                "Press <kbd>Esc</kbd> to exit pan mode."
            )
            pan_act.setStatusTip("Drag to move the view. Press Esc to exit.")
            pan_act.setIcon(QIcon(self.icon_path("Pan.svg")))
            pan_act.setShortcut(QKeySequence("P"))
            pan_act.setCheckable(True)

        if zoom_act:
            zoom_act.setText("Zoom")
            zoom_act.setToolTip(
                "<b>Zoom</b> <kbd>Z</kbd><br><br>"
                "Drag a rectangle to zoom in.<br>"
                "Press <kbd>Esc</kbd> to exit zoom mode."
            )
            zoom_act.setStatusTip("Drag a rectangle to zoom in. Press Esc to exit.")
            zoom_act.setIcon(QIcon(self.icon_path("Zoom.svg")))
            zoom_act.setShortcut(QKeySequence("Z"))
            zoom_act.setCheckable(True)

        # Hide subplots action
        if subplots_act:
            subplots_act.setVisible(False)

        # Remove save action
        if save_act:
            toolbar.removeAction(save_act)

        # Store actions
        self.actReset = home_act
        self.actBack = back_act
        self.actForward = forward_act
        self.actPan = pan_act
        self.actZoom = zoom_act

        # Add navigation actions
        if self.actReset:
            toolbar.addAction(self.actReset)
        if self.actBack:
            toolbar.addAction(self.actBack)
        if self.actForward:
            toolbar.addAction(self.actForward)

        toolbar.addSeparator()

        if self.actPan:
            toolbar.addAction(self.actPan)
        if self.actZoom:
            toolbar.addAction(self.actZoom)

        # Handle mutual exclusivity for pan/zoom
        self._nav_mode_actions = [act for act in (self.actPan, self.actZoom) if act is not None]
        for action in self._nav_mode_actions:
            with contextlib.suppress(Exception):
                action.toggled.disconnect(self._handle_nav_mode_toggled)
            action.toggled.connect(self._handle_nav_mode_toggled)

        toolbar.addSeparator()

        # Add Grid toggle
        self.actGrid = QAction(QIcon(self.icon_path("Grid.svg")), "Grid", self)
        self.actGrid.setCheckable(True)
        self.actGrid.setChecked(self.grid_visible)
        self.actGrid.setShortcut(QKeySequence("G"))
        self.actGrid.setToolTip(
            "<b>Toggle Grid</b> <kbd>G</kbd><br><br>"
            "Shows/hides coordinate grid overlay.<br>"
            "Use for precise alignment and measurements."
        )
        self.actGrid.triggered.connect(self._on_grid_toggled)
        toolbar.addAction(self.actGrid)

        # Add Style/Settings action
        self.actStyle = QAction(QIcon(self.icon_path("plot-settings.svg")), "Style", self)
        self.actStyle.setToolTip(
            "<b>Plot Settings</b><br><br>"
            "Open unified plot settings dialog.<br>"
            "Customize canvas, layout, axes, style, and event labels."
        )
        self.actStyle.triggered.connect(lambda: self._open_plot_settings_dialog(tab_name="style"))
        toolbar.addAction(self.actStyle)

        # Add Edit Points action
        self.actEditPoints = QAction(QIcon(self.icon_path("tour-pencil.svg")), "Edit Points", self)
        self.actEditPoints.setToolTip(
            "<b>Edit Points</b><br><br>"
            "Opens the Point Editor for manual trace correction.<br>"
            "Edit raw data points in the current view."
        )
        self.actEditPoints.setEnabled(self._trace_model is not None)  # Enable if trace loaded
        self.actEditPoints.triggered.connect(self._on_edit_points_triggered)
        toolbar.addAction(self.actEditPoints)

        # Add toolbar to window
        self.plot_toolbar = toolbar
        self.addToolBar(Qt.TopToolBarArea, toolbar)

    def _create_status_bar(self) -> None:
        """Create status bar with figure info and hints."""
        status_bar = self.statusBar()

        # Figure size label
        self._status_figure_size_label = QLabel("Figure: 0.0 × 0.0 in @ 0 DPI")
        self._status_figure_size_label.setMinimumWidth(200)
        status_bar.addWidget(self._status_figure_size_label)

        # Separator
        status_bar.addWidget(QLabel(" | "))

        # Canvas dimensions label
        self._status_dimensions_label = QLabel("Canvas: 0 × 0 px")
        self._status_dimensions_label.setMinimumWidth(150)
        status_bar.addWidget(self._status_dimensions_label)

        # Stretch to push hint to right side
        status_bar.addWidget(QLabel(), 1)

        # Hint label (right-aligned)
        self._status_hint_label = QLabel(
            "Double-click axes to edit • Use preset library for quick styles"
        )
        self._status_hint_label.setStyleSheet("color: gray;")
        status_bar.addPermanentWidget(self._status_hint_label)

    def _update_status_bar(self) -> None:
        """Update status bar with current figure information."""
        if not hasattr(self, "plot_host") or self.plot_host is None:
            return

        fig = self.plot_host.figure
        canvas = self.plot_host.canvas

        # Update figure size
        if hasattr(self, "_status_figure_size_label"):
            width_in = fig.get_figwidth()
            height_in = fig.get_figheight()
            dpi = int(fig.get_dpi())
            self._status_figure_size_label.setText(
                f"Figure: {width_in:.1f} × {height_in:.1f} in @ {dpi} DPI"
            )

        # Update canvas dimensions
        if hasattr(self, "_status_dimensions_label"):
            width_px = canvas.width()
            height_px = canvas.height()
            self._status_dimensions_label.setText(f"Canvas: {width_px} × {height_px} px")

    def _create_menus(self) -> None:
        """Create menu bar."""
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("&File")

        export_action = QAction("&Export Figure...", self)
        export_action.setShortcut("Ctrl+E")
        export_action.triggered.connect(self._on_export)
        file_menu.addAction(export_action)

        file_menu.addSeparator()

        close_action = QAction("&Close", self)
        close_action.setShortcut("Ctrl+W")
        close_action.triggered.connect(self.close)
        file_menu.addAction(close_action)

        # Edit menu
        edit_menu = menubar.addMenu("&Edit")

        undo_action = self.undo_stack.createUndoAction(self, "&Undo")
        undo_action.setShortcut("Ctrl+Z")
        edit_menu.addAction(undo_action)

        redo_action = self.undo_stack.createRedoAction(self, "&Redo")
        redo_action.setShortcut("Ctrl+Shift+Z")
        edit_menu.addAction(redo_action)

        # View menu
        self._view_menu = menubar.addMenu("&View")
        # NOTE: View menu currently empty - dock system removed

        # Tools menu
        tools_menu = menubar.addMenu("&Tools")

        edit_axes_action = QAction("Edit &Axes...", self)
        edit_axes_action.setShortcut("Ctrl+Shift+A")
        edit_axes_action.triggered.connect(self._on_edit_axes)
        tools_menu.addAction(edit_axes_action)

        edit_traces_action = QAction("Edit &Traces...", self)
        edit_traces_action.setShortcut("Ctrl+Shift+T")
        edit_traces_action.triggered.connect(self._on_edit_traces)
        tools_menu.addAction(edit_traces_action)

        tools_menu.addSeparator()

        reset_view_action = QAction("&Reset View", self)
        reset_view_action.setShortcut("Ctrl+R")
        reset_view_action.triggered.connect(self._on_reset_view)
        tools_menu.addAction(reset_view_action)

        fit_data_action = QAction("&Fit to Data", self)
        fit_data_action.setShortcut("Ctrl+F")
        fit_data_action.triggered.connect(self._on_fit_data)
        tools_menu.addAction(fit_data_action)

        # Epochs menu
        epochs_menu = menubar.addMenu("E&pochs")

        auto_generate_action = QAction("&Auto-Generate from Events", self)
        auto_generate_action.setShortcut("Ctrl+G")
        auto_generate_action.triggered.connect(self._on_auto_generate_epochs)
        epochs_menu.addAction(auto_generate_action)

        edit_epochs_action = QAction("&Edit Epochs...", self)
        edit_epochs_action.setShortcut("Ctrl+E")
        edit_epochs_action.triggered.connect(self._on_edit_epochs)
        epochs_menu.addAction(edit_epochs_action)

        epochs_menu.addSeparator()

        toggle_epochs_action = QAction("&Show Epoch Overlays", self)
        toggle_epochs_action.setCheckable(True)
        toggle_epochs_action.setChecked(self._epochs_visible)
        toggle_epochs_action.triggered.connect(self._on_toggle_epochs)
        epochs_menu.addAction(toggle_epochs_action)
        self._toggle_epochs_action = toggle_epochs_action

        # Presets menu
        presets_menu = menubar.addMenu("&Presets")

        save_preset_action = QAction("&Save Current as Preset...", self)
        save_preset_action.triggered.connect(self._on_save_preset)
        presets_menu.addAction(save_preset_action)

        load_preset_action = QAction("&Load Preset...", self)
        load_preset_action.triggered.connect(self._on_load_preset)
        presets_menu.addAction(load_preset_action)

        # Help menu
        help_menu = menubar.addMenu("&Help")

        about_action = QAction("&About Figure Composer", self)
        about_action.triggered.connect(self._on_about)
        help_menu.addAction(about_action)

    def _apply_theme(self) -> None:
        """Apply current theme colors to window."""
        bg = CURRENT_THEME.get("window_bg", "#FFFFFF")
        text = CURRENT_THEME.get("text", "#000000")
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {bg};
                color: {text};
            }}
            QMenuBar {{
                background-color: {bg};
                color: {text};
            }}
            QMenu {{
                background-color: {bg};
                color: {text};
            }}
        """)

    # ------------------------------------------------------------------ Plot Management

    def _populate_plot_host(self) -> None:
        """Populate PlotHost with cloned trace data and events."""
        if not self._trace_model:
            return

        # Set trace model
        self.plot_host.set_trace_model(self._trace_model)

        # Ensure channels
        if self._channel_specs:
            self.plot_host.ensure_channels(self._channel_specs)

        # Set events
        self.plot_host.set_events(
            self._event_times,
            self._event_colors,
            self._event_labels,
            self._event_label_meta,
        )

        # Initialize epoch layer
        self._epoch_layer = EpochLayer(
            epochs=self._epochs,
            theme=self._epoch_theme,
        )
        if self._epochs_visible:
            primary_ax = self._get_primary_axes()
            if primary_ax is not None:
                self._epoch_layer.attach(primary_ax)

        # Apply layout state
        # Note: Layout is applied via channel specs - no dock needed

        # Apply initial style
        if self._style_manager:
            self._apply_style_to_plot()

        # Refresh canvas
        self.plot_host.canvas.draw_idle()
        self._sync_canvas_size_to_figure()

        # Update toolbar state
        self._update_toolbar_state()

    def _update_toolbar_state(self) -> None:
        """Update toolbar button states based on current data."""
        # Enable/disable Edit Points based on trace data availability
        if hasattr(self, "actEditPoints"):
            self.actEditPoints.setEnabled(self._trace_model is not None)

    def _apply_style_to_plot(self) -> None:
        """Apply current style manager settings to PlotHost."""
        if not self._style_manager or not hasattr(self, "plot_host"):
            return

        style = self._style_manager.style()
        defaults = DEFAULT_STYLE
        plot_host = self.plot_host
        if plot_host is None:
            return

        x_axis = self._x_axis_for_style()
        v3_enabled = bool(
            style.get("event_labels_v3_enabled", defaults.get("event_labels_v3_enabled", True))
        )
        event_objects = [] if v3_enabled else self.event_text_objects

        remaining_event_objects = event_objects if event_objects else None
        tracks = getattr(plot_host, "tracks", None)
        track_iter = tracks() if callable(tracks) else list(plot_host._tracks.values())

        for index, track in enumerate(track_iter):
            ax = getattr(track, "ax", None)
            if ax is None:
                continue

            if self.grid_visible:
                ax.grid(True, color=CURRENT_THEME.get("grid_color", "#e0e0e0"))
            else:
                ax.grid(False)

            view = getattr(track, "view", track)
            ax_secondary = getattr(view, "ax2", None)
            main_line = getattr(view, "inner_line", None)
            od_line = getattr(view, "outer_line", None)

            self._style_manager.apply(
                ax=ax,
                ax_secondary=ax_secondary,
                x_axis=x_axis,
                event_text_objects=remaining_event_objects if index == 0 else None,
                pinned_points=None,
                main_line=main_line,
                od_line=od_line,
            )

        plot_host.suspend_updates()
        try:
            with contextlib.suppress(Exception):
                plot_host.set_event_labels_v3_enabled(v3_enabled)
            with contextlib.suppress(Exception):
                plot_host.set_event_label_mode(
                    style.get("event_label_mode", defaults.get("event_label_mode", "vertical"))
                )
            with contextlib.suppress(Exception):
                plot_host.set_max_labels_per_cluster(
                    style.get(
                        "event_label_max_per_cluster",
                        defaults.get("event_label_max_per_cluster", 1),
                    )
                )
            with contextlib.suppress(Exception):
                plot_host.set_cluster_style_policy(
                    style.get(
                        "event_label_style_policy",
                        defaults.get("event_label_style_policy", "first"),
                    )
                )
            with contextlib.suppress(Exception):
                plot_host.set_label_lanes(
                    style.get("event_label_lanes", defaults.get("event_label_lanes", 3))
                )
            with contextlib.suppress(Exception):
                plot_host.set_belt_baseline(
                    style.get(
                        "event_label_belt_baseline",
                        defaults.get("event_label_belt_baseline", True),
                    )
                )
            with contextlib.suppress(Exception):
                plot_host.set_event_label_span_siblings(
                    style.get(
                        "event_label_span_siblings",
                        defaults.get("event_label_span_siblings", True),
                    )
                )
            with contextlib.suppress(Exception):
                plot_host.set_auto_event_label_mode(
                    style.get(
                        "event_label_auto_mode",
                        defaults.get("event_label_auto_mode", False),
                    )
                )
            with contextlib.suppress(Exception):
                plot_host.set_label_density_thresholds(
                    compact=style.get(
                        "event_label_density_compact",
                        defaults.get("event_label_density_compact", 0.8),
                    ),
                    belt=style.get(
                        "event_label_density_belt",
                        defaults.get("event_label_density_belt", 0.25),
                    ),
                )
            outline_enabled = style.get(
                "event_label_outline_enabled",
                defaults.get("event_label_outline_enabled", True),
            )
            outline_width = style.get(
                "event_label_outline_width",
                defaults.get("event_label_outline_width", 2.0),
            )
            outline_color = style.get(
                "event_label_outline_color",
                defaults.get("event_label_outline_color", "#FFFFFFFF"),
            )
            with contextlib.suppress(Exception):
                plot_host.set_label_outline_enabled(outline_enabled)
            with contextlib.suppress(Exception):
                plot_host.set_label_outline(outline_width, outline_color)
            with contextlib.suppress(Exception):
                plot_host.set_label_tooltips_enabled(
                    style.get(
                        "event_label_tooltips_enabled",
                        defaults.get("event_label_tooltips_enabled", True),
                    )
                )
            with contextlib.suppress(Exception):
                plot_host.set_tooltip_proximity(
                    style.get(
                        "event_label_tooltip_proximity",
                        defaults.get("event_label_tooltip_proximity", 10),
                    )
                )
            with contextlib.suppress(Exception):
                plot_host.set_compact_legend_enabled(
                    style.get(
                        "event_label_legend_enabled",
                        defaults.get("event_label_legend_enabled", True),
                    )
                )
            with contextlib.suppress(Exception):
                plot_host.set_compact_legend_location(
                    style.get(
                        "event_label_legend_location",
                        style.get(
                            "event_label_legend_loc",
                            defaults.get("event_label_legend_loc", "upper right"),
                        ),
                    )
                )
            with contextlib.suppress(Exception):
                plot_host.set_event_base_style(
                    font_family=style.get(
                        "event_font_family", defaults.get("event_font_family", "Arial")
                    ),
                    font_size=style.get("event_font_size", defaults.get("event_font_size", 15)),
                    bold=style.get("event_bold", defaults.get("event_bold", False)),
                    italic=style.get("event_italic", defaults.get("event_italic", False)),
                    color=style.get("event_color", defaults.get("event_color", "#000000")),
                )
            highlight_color = style.get(
                "event_highlight_color",
                self._event_highlight_color,
            )
            highlight_alpha = float(style.get("event_highlight_alpha", self._event_highlight_alpha))
            with contextlib.suppress(Exception):
                plot_host.set_event_highlight_style(color=highlight_color, alpha=highlight_alpha)
            self._event_highlight_color = str(highlight_color)
            self._event_highlight_alpha = float(highlight_alpha)
            self._event_highlight_duration_ms = int(
                style.get(
                    "event_highlight_duration_ms",
                    self._event_highlight_duration_ms,
                )
            )
        finally:
            plot_host.resume_updates()

    def apply_plot_style(self, style: dict[str, Any] | None, persist: bool = False) -> None:
        """Apply a new style dictionary to the publication plot."""
        incoming = style or {}
        if self._style_manager is None:
            base = DEFAULT_STYLE.copy()
            base.update(incoming)
            self._style_manager = PlotStyleManager(base)
        else:
            self._style_manager.update(incoming)

        if persist:
            self._current_preset_name = None

        self._apply_style_to_plot()
        self._sync_canvas_size_to_figure()

        if hasattr(self, "plot_host") and self.plot_host is not None:
            self.plot_host.canvas.draw_idle()

    def _snapshot_style(
        self,
        ax=None,
        ax2=None,
        event_text_objects=None,
        pinned_points=None,
        od_line=None,
    ) -> dict[str, Any]:
        """Capture the current style from the active plot."""
        style: dict[str, Any] = dict(DEFAULT_STYLE)
        primary_ax = ax or self._get_primary_axes()
        if primary_ax is None:
            return style

        track_for_ax = None
        if hasattr(self, "plot_host") and self.plot_host is not None:
            for track in self.plot_host.tracks():
                if getattr(track, "ax", None) is primary_ax:
                    track_for_ax = track
                    break

        view = getattr(track_for_ax, "view", None)
        secondary_ax = ax2 or (getattr(view, "ax2", None) if view else None)
        x_axis = self._x_axis_for_style() or primary_ax

        x_label = x_axis.xaxis.label
        y_label = primary_ax.yaxis.label
        style["axis_font_size"] = x_label.get_fontsize()
        style["axis_font_family"] = x_label.get_fontname()
        style["axis_bold"] = str(x_label.get_fontweight()).lower() == "bold"
        style["axis_italic"] = x_label.get_fontstyle() == "italic"
        style["axis_color"] = x_label.get_color()
        style["x_axis_color"] = x_label.get_color()
        style["y_axis_color"] = y_label.get_color()

        x_tick_labels = x_axis.get_xticklabels()
        y_tick_labels = primary_ax.get_yticklabels()
        tick_font_size = (
            x_tick_labels[0].get_fontsize()
            if x_tick_labels
            else (y_tick_labels[0].get_fontsize() if y_tick_labels else style["tick_font_size"])
        )
        style["tick_font_size"] = tick_font_size

        x_tick_color = x_tick_labels[0].get_color() if x_tick_labels else style["x_tick_color"]
        y_tick_color = y_tick_labels[0].get_color() if y_tick_labels else style["y_tick_color"]
        style["tick_color"] = x_tick_color
        style["x_tick_color"] = x_tick_color
        style["y_tick_color"] = y_tick_color

        try:
            major_ticks = x_axis.xaxis.get_major_ticks()
            if major_ticks:
                style["tick_length"] = float(major_ticks[0].tick1line.get_markersize())
                style["tick_width"] = float(major_ticks[0].tick1line.get_linewidth())
        except Exception:
            pass

        if view is not None and getattr(view, "inner_line", None) is not None:
            inner_line = view.inner_line
            style["line_width"] = inner_line.get_linewidth()
            style["line_color"] = inner_line.get_color()
            style["line_style"] = inner_line.get_linestyle()
        elif primary_ax.lines:
            line = primary_ax.lines[0]
            style["line_width"] = line.get_linewidth()
            style["line_color"] = line.get_color()
            style["line_style"] = line.get_linestyle()

        event_objects = event_text_objects
        if event_objects is None:
            event_objects = self.event_text_objects
        if event_objects:
            txt = event_objects[0][0]
            style["event_font_size"] = txt.get_fontsize()
            style["event_font_family"] = txt.get_fontname()
            style["event_bold"] = str(txt.get_fontweight()).lower() == "bold"
            style["event_italic"] = txt.get_fontstyle() == "italic"
            style["event_color"] = txt.get_color()

        if secondary_ax is not None:
            y2_label = secondary_ax.yaxis.label
            style["right_axis_color"] = y2_label.get_color()
            y2_ticks = secondary_ax.get_yticklabels()
            if y2_ticks:
                style["right_tick_color"] = y2_ticks[0].get_color()
            od_artist = od_line
            if od_artist is None and view is not None:
                od_artist = getattr(view, "outer_line", None)
            if od_artist is not None:
                style["outer_line_width"] = od_artist.get_linewidth()
                style["outer_line_color"] = od_artist.get_color()
                style["outer_line_style"] = od_artist.get_linestyle()

        style["event_highlight_color"] = self._event_highlight_color
        style["event_highlight_alpha"] = self._event_highlight_alpha
        style["event_highlight_duration_ms"] = self._event_highlight_duration_ms

        plot_host = getattr(self, "plot_host", None)
        if plot_host is not None:
            style["event_labels_v3_enabled"] = plot_host.event_labels_v3_enabled()
            style["event_label_max_per_cluster"] = plot_host.max_labels_per_cluster()
            style["event_label_style_policy"] = plot_host.cluster_style_policy()
            style["event_label_lanes"] = plot_host.event_label_lanes()
            style["event_label_belt_baseline"] = plot_host.belt_baseline_enabled()
            style["event_label_span_siblings"] = plot_host.span_event_lines_across_siblings()
            style["event_label_auto_mode"] = plot_host.auto_event_label_mode()
            compact_thr, belt_thr = plot_host.label_density_thresholds()
            style["event_label_density_compact"] = compact_thr
            style["event_label_density_belt"] = belt_thr
            outline_enabled, outline_width, outline_color = plot_host.label_outline_settings()
            style["event_label_outline_enabled"] = outline_enabled
            style["event_label_outline_width"] = outline_width
            style["event_label_outline_color"] = outline_color or DEFAULT_STYLE.get(
                "event_label_outline_color", "#FFFFFFFF"
            )
            style["event_label_tooltips_enabled"] = plot_host.label_tooltips_enabled()
            style["event_label_tooltip_proximity"] = plot_host.tooltip_proximity()
            style["event_label_legend_enabled"] = plot_host.compact_legend_enabled()
            style["event_label_legend_location"] = plot_host.compact_legend_location()
        else:
            style.setdefault(
                "event_labels_v3_enabled",
                DEFAULT_STYLE.get("event_labels_v3_enabled", True),
            )
            style.setdefault(
                "event_label_max_per_cluster",
                DEFAULT_STYLE.get("event_label_max_per_cluster", 1),
            )
            style.setdefault(
                "event_label_style_policy",
                DEFAULT_STYLE.get("event_label_style_policy", "first"),
            )
            style.setdefault(
                "event_label_lanes",
                DEFAULT_STYLE.get("event_label_lanes", 3),
            )
            style.setdefault(
                "event_label_belt_baseline",
                DEFAULT_STYLE.get("event_label_belt_baseline", True),
            )
            style.setdefault(
                "event_label_span_siblings",
                DEFAULT_STYLE.get("event_label_span_siblings", True),
            )
            style.setdefault(
                "event_label_auto_mode",
                DEFAULT_STYLE.get("event_label_auto_mode", False),
            )
            style.setdefault(
                "event_label_density_compact",
                DEFAULT_STYLE.get("event_label_density_compact", 0.8),
            )
            style.setdefault(
                "event_label_density_belt",
                DEFAULT_STYLE.get("event_label_density_belt", 0.25),
            )
            style.setdefault(
                "event_label_outline_enabled",
                DEFAULT_STYLE.get("event_label_outline_enabled", True),
            )
            style.setdefault(
                "event_label_outline_width",
                DEFAULT_STYLE.get("event_label_outline_width", 2.0),
            )
            style.setdefault(
                "event_label_outline_color",
                DEFAULT_STYLE.get("event_label_outline_color", "#FFFFFFFF"),
            )

        return style

    # ------------------------------------------------------------------ Actions

    def _on_export(self, checked: bool = False) -> None:
        """Export current figure to file.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
        import json
        from pathlib import Path

        from PyQt5.QtWidgets import QFileDialog

        # Get export format and path
        file_filter = "TIFF Files (*.tiff);;SVG Files (*.svg);;PNG Files (*.png);;PDF Files (*.pdf)"
        output_path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export Figure",
            "figure.tiff",
            file_filter,
        )

        if not output_path:
            return

        # Determine DPI based on format
        dpi = 300  # Default high-quality DPI

        try:
            # Export figure
            self.plot_host.figure.savefig(
                output_path,
                dpi=dpi,
                bbox_inches="tight",
                pad_inches=0.1,
            )

            # Save epoch metadata as sidecar JSON if epochs exist
            if self._epochs and self._epoch_layer is not None:
                manifest = self._epoch_layer.to_manifest()
                metadata_path = Path(output_path).with_suffix(".epochs.json")
                with open(metadata_path, "w") as f:
                    json.dump(manifest, f, indent=2)

            QMessageBox.information(
                self,
                "Export Successful",
                f"Figure exported successfully to:\n{output_path}"
                + (f"\nEpoch metadata saved to:\n{metadata_path}" if self._epochs else ""),
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Export Failed",
                f"Failed to export figure:\n{str(e)}",
            )

    def _on_save_preset(self, checked: bool = False) -> None:
        """Save current style as preset.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
        # TODO: Implement preset save dialog when preset system is integrated
        QMessageBox.information(
            self,
            "Save Preset",
            "Preset save functionality will be available in the Inspector panel.",
        )

    def _on_load_preset(self, checked: bool = False) -> None:
        """Load a preset.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
        # Use the preset combo in the toolbar
        QMessageBox.information(
            self,
            "Load Preset",
            "Please use the Preset dropdown in the toolbar to select and apply presets.",
        )

    def _on_about(self, checked: bool = False) -> None:
        """Show about dialog.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
        QMessageBox.about(
            self,
            "About Figure Composer",
            "<h3>Figure Composer</h3>"
            "<p>Advanced figure styling and export workspace for VasoAnalyzer.</p>"
            "<p>Features:</p>"
            "<ul>"
            "<li>Live preview with embedded PlotHost</li>"
            "<li>Advanced styling controls</li>"
            "<li>Style preset library</li>"
            "<li>Batch export queue</li>"
            "<li>Undo/redo for styling operations</li>"
            "<li>Protocol epoch timeline overlays</li>"
            "</ul>"
            "<p><b>Version:</b> 1.0.0-alpha</p>",
        )

    def _on_auto_generate_epochs(self, checked: bool = False) -> None:
        """Auto-generate epochs from event data.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
        if not self._event_times:
            QMessageBox.information(
                self,
                "No Events",
                "No events found to generate epochs from.\n\n"
                "Please load event data in the main window before generating epochs.",
            )
            return

        self.auto_generate_epochs()

        QMessageBox.information(
            self,
            "Epochs Generated",
            f"Successfully generated {len(self._epochs)} epoch(s) from event data.\n\n"
            "Use the Epochs menu to toggle visibility or edit individual epochs.",
        )

    def _on_toggle_epochs(self, checked: bool) -> None:
        """Toggle epoch overlay visibility.

        Args:
            checked: Visibility state from checkbox
        """
        self.toggle_epochs_visibility(checked)

    def _on_edit_epochs(self, checked: bool = False) -> None:
        """Open epoch editor dialog.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
        editor = EpochEditorDialog(self._epochs, self)
        editor.epochs_changed.connect(self._on_epochs_edited)
        editor.show()

    def _on_epochs_edited(self, epochs: list[Epoch]) -> None:
        """Handle epochs edited in the editor dialog."""
        self.set_epochs(epochs)

    def _open_plot_settings_dialog(self, *, tab_name: str | None = None) -> None:
        """Open the unified plot settings dialog focused on an optional tab."""
        primary_ax = self._get_primary_axes()
        if primary_ax is None:
            QMessageBox.information(
                self,
                "No Plot Available",
                "Load a trace before editing plot settings.",
            )
            return

        secondary_ax = None
        for track in self.plot_host.tracks():
            view = getattr(track, "view", None)
            candidate = getattr(view, "ax2", None)
            if candidate is not None:
                secondary_ax = candidate
                break

        dialog = UnifiedPlotSettingsDialog(
            self,
            primary_ax,
            self.plot_host.canvas,
            ax2=secondary_ax,
            event_text_objects=self.event_text_objects,
            pinned_points=None,
        )
        dialog.set_event_update_callback(self.apply_event_label_overrides)

        if tab_name:
            mapping = {
                "canvas": 0,
                "frame": 0,
                "layout": 1,
                "axis": 2,
                "axes": 2,
                "style": 3,
                "event_labels": 4,
            }
            idx = mapping.get(str(tab_name).lower(), 0)
            with contextlib.suppress(Exception):
                dialog.tabs.setCurrentIndex(idx)

        old_style = self.get_current_style()
        result = dialog.exec_()
        self._sync_canvas_size_to_figure()

        if result == QDialog.Accepted:
            new_style = self.get_current_style()
            if new_style != old_style and self._style_manager is not None:
                command = StyleChangeCommand(self, old_style, new_style, "Adjust Plot Settings")
                self.undo_stack.push(command)

    def _on_edit_axes(self, checked: bool = False) -> None:
        """Open axis editor dialog.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
        self._open_plot_settings_dialog(tab_name="axis")

    def _on_edit_traces(self, checked: bool = False) -> None:
        """Open trace editor dialog.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
        self._open_plot_settings_dialog(tab_name="style")

    def _on_reset_view(self, checked: bool = False) -> None:
        """Reset view to full data range.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
        if self._trace_model is None:
            return

        # Reset to full time range
        t_min, t_max = self._trace_model.full_range
        self.plot_host.set_time_window(t_min, t_max)

        # Reset Y-axes to autoscale
        for track in self.plot_host._tracks.values():
            if hasattr(track, "ax") and track.ax is not None:
                track.ax.autoscale(axis="y")

        self.plot_host.canvas.draw_idle()

    def _on_fit_data(self, checked: bool = False) -> None:
        """Auto-fit all axes to data range.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
        # Autoscale all axes
        for track in self.plot_host._tracks.values():
            if hasattr(track, "ax") and track.ax is not None:
                track.ax.autoscale()

        self.plot_host.canvas.draw_idle()

    def _on_canvas_size_changed(self, index: int) -> None:
        """Handle canvas size preset change."""
        if index < 0:
            return

        size_data = self.canvas_size_combo.itemData(index)
        if size_data:
            self._canvas_width_in, self._canvas_height_in = size_data
            self._apply_canvas_size()

    def _on_preset_combo_changed(self, index: int) -> None:
        """Handle style preset selection from combo box."""
        if index <= 0:  # Skip "(Select Preset)" item
            return

        preset_name = self.preset_combo.itemText(index)
        # Find preset by name in built-in presets
        for preset in self._builtin_presets:
            if preset.get("name") == preset_name:
                self.apply_preset(preset)
                break

        # Reset combo to placeholder
        self.preset_combo.blockSignals(True)
        self.preset_combo.setCurrentIndex(0)
        self.preset_combo.blockSignals(False)

    def _on_zoom_in(self, checked: bool = False) -> None:
        """Zoom in to the next zoom level."""
        current_idx = self.zoom_combo.currentIndex()
        # Don't go past the last regular zoom level (before "Fit")
        if current_idx < len(self._zoom_levels) - 1:
            self.zoom_combo.setCurrentIndex(current_idx + 1)

    def _on_zoom_out(self, checked: bool = False) -> None:
        """Zoom out to the previous zoom level."""
        current_idx = self.zoom_combo.currentIndex()
        if current_idx > 0:
            self.zoom_combo.setCurrentIndex(current_idx - 1)

    def _on_zoom_changed(self, index: int) -> None:
        """Handle zoom level change from combo box."""
        zoom_value = self.zoom_combo.itemData(index)

        if zoom_value == "fit":
            # Fit canvas in view
            if hasattr(self, "canvas_view") and hasattr(self, "canvas_item"):
                self.canvas_view.fit_in_view(self.canvas_item.rect())
        else:
            # Zoom to specific level
            zoom_level = float(zoom_value)
            if hasattr(self, "canvas_view"):
                self.canvas_view.zoom_to_level(zoom_level)

    def _handle_nav_mode_toggled(self, checked: bool) -> None:
        """Handle mutual exclusivity between pan and zoom modes."""
        if not checked:
            return

        sender = self.sender()
        if sender is None:
            return

        # Uncheck all other navigation mode actions
        for action in self._nav_mode_actions:
            if action is not sender and action.isChecked():
                action.blockSignals(True)
                action.setChecked(False)
                action.blockSignals(False)

    def _on_grid_toggled(self, checked: bool) -> None:
        """Handle grid toggle action."""
        self.grid_visible = checked
        # Update grid visibility on all axes
        for track in self.plot_host._tracks.values():
            ax = getattr(track, "ax", None)
            if ax is not None:
                if self.grid_visible:
                    ax.grid(True, color=CURRENT_THEME.get("grid_color", "#e0e0e0"))
                else:
                    ax.grid(False)
        self.plot_host.canvas.draw_idle()

    def _on_edit_points_triggered(self, checked: bool = False) -> None:
        """Handle edit points action - opens point editor for manual trace correction."""
        if not self._trace_model:
            QMessageBox.information(
                self,
                "No Trace Data",
                "Please load trace data before using the point editor.",
            )
            return

        # TODO: Implement point editor integration
        QMessageBox.information(
            self,
            "Edit Points",
            "Point editor integration coming soon.\n\n"
            "This feature will allow manual correction of trace data points.",
        )

    # ------------------------------------------------------------------ Dock Signal Handlers
    # NOTE: Old dock signal handlers removed - functionality will be moved to panels

    # def _on_preset_load_requested(self, preset: dict[str, Any]) -> None:
    #     """Handle preset load request."""
    #     self.apply_preset(preset)
    #
    # def _on_preset_save_requested(self, name: str, description: str, tags: list[str]) -> None:
    #     """Handle preset save request."""
    #     preset = self.save_current_as_preset(name, description, tags)
    #
    # def _on_style_changed(self, style: dict[str, Any]) -> None:
    #     """Handle style change."""
    #     if self._style_manager:
    #         self._style_manager.update(style)
    #
    # def _on_layout_changed(self, layout_state: LayoutState) -> None:
    #     """Handle layout change."""
    #     pass
    #
    # def _on_export_requested(self, jobs: list) -> None:
    #     """Handle batch export request."""
    #     pass

    # ------------------------------------------------------------------ Event Handlers

    def closeEvent(self, event: QCloseEvent) -> None:
        """Handle window close event."""
        # Check for unsaved changes (future enhancement)
        self.studio_closed.emit()
        super().closeEvent(event)
