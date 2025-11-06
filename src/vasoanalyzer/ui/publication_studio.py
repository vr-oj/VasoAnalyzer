"""Publication Studio - Advanced figure styling and export workspace."""

from __future__ import annotations

from typing import Any, cast

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QCloseEvent
from PyQt5.QtWidgets import (
    QAction,
    QMainWindow,
    QMessageBox,
    QSizePolicy,
    QUndoStack,
    QVBoxLayout,
    QWidget,
)

from vasoanalyzer.core.trace_model import TraceModel
from vasoanalyzer.ui.builtin_presets import get_builtin_presets
from vasoanalyzer.ui.docks.advanced_style_dock import AdvancedStyleDock
from vasoanalyzer.ui.docks.export_queue_dock import ExportQueueDock
from vasoanalyzer.ui.docks.layout_dock import LayoutDock
from vasoanalyzer.ui.docks.preset_library_dock import PresetLibraryDock
from vasoanalyzer.ui.plots.channel_track import ChannelTrackSpec
from vasoanalyzer.ui.plots.plot_host import LayoutState, PlotHost
from vasoanalyzer.ui.style_manager import PlotStyleManager
from vasoanalyzer.ui.theme import CURRENT_THEME

__all__ = ["PublicationStudioWindow"]


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
        self.setWindowTitle("Publication Studio")
        self.setObjectName("PublicationStudioWindow")

        # Core state
        self._trace_model: TraceModel | None = None
        self._event_times: list[float] = []
        self._event_colors: list[str] | None = None
        self._event_labels: list[str] = []
        self._event_label_meta: list[dict[str, Any]] = []
        self._channel_specs: list[ChannelTrackSpec] = []
        self._layout_state: LayoutState | None = None

        # Style management
        self._style_manager: PlotStyleManager | None = None
        self._current_preset_name: str | None = None

        # Undo/redo stack for styling operations
        self.undo_stack = QUndoStack(self)

        # Build UI
        self._build_ui()
        self._create_menus()
        self._create_dock_areas()

        # Apply theme
        self._apply_theme()

        # Restore window geometry
        self.resize(1400, 900)

    # ------------------------------------------------------------------ Public API

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
                display_name=spec.display_name,
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

    def get_current_style(self) -> dict[str, Any]:
        """Snapshot current plot style from PlotHost artists."""
        if self._style_manager:
            return cast(dict[str, Any], self._style_manager.style())
        return {}

    def apply_preset(self, preset: dict[str, Any]) -> None:
        """
        Apply a style preset to the current figure.

        Args:
            preset: Preset dictionary (must contain "style" key)
        """
        if not self._style_manager:
            self._style_manager = PlotStyleManager()

        # Use PlotStyleManager's from_preset method
        self._style_manager.from_preset(preset)

        self._apply_style_to_plot()
        self._current_preset_name = preset.get("name")

        # Update style dock with new style
        if hasattr(self, "_advanced_style_dock"):
            self._advanced_style_dock.set_style(self._style_manager.style())

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
        """Build central widget with PlotHost preview."""
        central_widget = QWidget(self)
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)

        # Embedded PlotHost for live preview
        self.plot_host = PlotHost(dpi=120)
        self.plot_host.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.plot_host.canvas)

        self.setCentralWidget(central_widget)

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
        view_menu = menubar.addMenu("&View")
        self._view_menu = view_menu  # Store for dock toggles

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

        about_action = QAction("&About Publication Studio", self)
        about_action.triggered.connect(self._on_about)
        help_menu.addAction(about_action)

    def _create_dock_areas(self) -> None:
        """
        Create dockable panel areas.

        Docks layout:
        - Left: Preset Library
        - Right: Advanced Style, Layout, Export Queue (tabbed)
        """
        # Set dock nesting and corners
        self.setDockNestingEnabled(True)
        self.setCorner(Qt.TopLeftCorner, Qt.LeftDockWidgetArea)
        self.setCorner(Qt.BottomLeftCorner, Qt.LeftDockWidgetArea)
        self.setCorner(Qt.TopRightCorner, Qt.RightDockWidgetArea)
        self.setCorner(Qt.BottomRightCorner, Qt.RightDockWidgetArea)

        # Preset Library Dock (left side)
        self._preset_library_dock = PresetLibraryDock(self)
        self.addDockWidget(Qt.LeftDockWidgetArea, self._preset_library_dock)

        # Load built-in presets
        built_in_presets = get_builtin_presets()
        self._preset_library_dock.set_presets([], built_in_presets)

        # Connect preset library signals
        self._preset_library_dock.preset_load_requested.connect(self._on_preset_load_requested)
        self._preset_library_dock.preset_save_requested.connect(self._on_preset_save_requested)
        self._preset_library_dock.preset_delete_requested.connect(self._on_preset_delete_requested)

        # Advanced Style Dock (right side)
        self._advanced_style_dock = AdvancedStyleDock(self)
        self.addDockWidget(Qt.RightDockWidgetArea, self._advanced_style_dock)

        # Connect style dock signals
        self._advanced_style_dock.style_changed.connect(self._on_style_changed)
        self._advanced_style_dock.apply_requested.connect(self._on_style_apply)
        self._advanced_style_dock.revert_requested.connect(self._on_style_revert)

        # Layout Dock (right side, tabified)
        self._layout_dock = LayoutDock(self)
        self.addDockWidget(Qt.RightDockWidgetArea, self._layout_dock)
        self.tabifyDockWidget(self._advanced_style_dock, self._layout_dock)

        # Connect layout dock signals
        self._layout_dock.layout_changed.connect(self._on_layout_changed)
        self._layout_dock.margins_changed.connect(self._on_margins_changed)

        # Export Queue Dock (right side, tabified)
        self._export_queue_dock = ExportQueueDock(self)
        self.addDockWidget(Qt.RightDockWidgetArea, self._export_queue_dock)
        self.tabifyDockWidget(self._layout_dock, self._export_queue_dock)

        # Connect export dock signals
        self._export_queue_dock.export_requested.connect(self._on_export_requested)

        # Add dock toggle actions to View menu
        self._view_menu.addAction(self._preset_library_dock.toggleViewAction())
        self._view_menu.addAction(self._advanced_style_dock.toggleViewAction())
        self._view_menu.addAction(self._layout_dock.toggleViewAction())
        self._view_menu.addAction(self._export_queue_dock.toggleViewAction())

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

        # Apply layout state
        if self._layout_state:
            self.plot_host.set_layout_state(self._layout_state)
            # Update layout dock
            if hasattr(self, "_layout_dock"):
                self._layout_dock.set_layout_state(self._layout_state)

        # Apply initial style
        if self._style_manager:
            self._apply_style_to_plot()
            # Update style dock
            if hasattr(self, "_advanced_style_dock"):
                self._advanced_style_dock.set_style(self._style_manager._style)

        # Refresh canvas
        self.plot_host.canvas.draw_idle()

    def _apply_style_to_plot(self) -> None:
        """Apply current style manager settings to PlotHost."""
        if not self._style_manager:
            return

        # TODO: Extract artists from PlotHost and call style_manager.apply()
        # This requires accessing PlotHost's internal axes, lines, text objects
        # Will be implemented once we have style panel controls
        pass

    # ------------------------------------------------------------------ Actions

    def _on_export(self) -> None:
        """Export current figure (placeholder)."""
        QMessageBox.information(
            self,
            "Export",
            "Export functionality will be implemented in Phase 4 (Batch Exporter).",
        )

    def _on_save_preset(self) -> None:
        """Save current style as preset (placeholder)."""
        QMessageBox.information(
            self,
            "Save Preset",
            "Preset save will be implemented in Phase 3 (Style Preset System).",
        )

    def _on_load_preset(self) -> None:
        """Load a saved preset (placeholder)."""
        QMessageBox.information(
            self,
            "Load Preset",
            "Preset loading will be implemented in Phase 3 (Style Preset System).",
        )

    def _on_about(self) -> None:
        """Show about dialog."""
        QMessageBox.about(
            self,
            "About Publication Studio",
            "<h3>Publication Studio</h3>"
            "<p>Advanced figure styling and export workspace for VasoAnalyzer.</p>"
            "<p>Features:</p>"
            "<ul>"
            "<li>Live preview with embedded PlotHost</li>"
            "<li>Advanced styling controls</li>"
            "<li>Style preset library</li>"
            "<li>Batch export queue</li>"
            "<li>Undo/redo for styling operations</li>"
            "</ul>"
            "<p><b>Version:</b> 1.0.0-alpha</p>",
        )

    # ------------------------------------------------------------------ Dock Signal Handlers

    def _on_preset_load_requested(self, preset: dict[str, Any]) -> None:
        """Handle preset load request."""
        self.apply_preset(preset.get("style", {}))

    def _on_preset_save_requested(self, name: str, description: str, tags: list[str]) -> None:
        """Handle preset save request."""
        preset = self.save_current_as_preset(name, description, tags)
        # Update preset library
        if hasattr(self, "_preset_library_dock"):
            self._preset_library_dock.add_preset(preset)

    def _on_preset_delete_requested(self, name: str) -> None:
        """Handle preset delete request."""
        # Deletion handled by PresetLibraryDock internally
        pass

    def _on_style_changed(self, style: dict[str, Any]) -> None:
        """Handle style change from AdvancedStyleDock."""
        # Update internal style (don't apply yet - wait for Apply button)
        if self._style_manager:
            self._style_manager.update(style)

    def _on_style_apply(self) -> None:
        """Apply current style to plot."""
        self._apply_style_to_plot()
        self.plot_host.canvas.draw_idle()

    def _on_style_revert(self) -> None:
        """Revert to previous style."""
        # TODO: Implement undo/redo
        QMessageBox.information(self, "Revert", "Undo/redo will be implemented in Phase 5.")

    def _on_layout_changed(self, layout_state: LayoutState) -> None:
        """Handle layout change from LayoutDock."""
        if hasattr(self.plot_host, "set_layout_state"):
            self.plot_host.set_layout_state(layout_state)
            self.plot_host.canvas.draw_idle()

    def _on_margins_changed(self, margins: dict[str, float]) -> None:
        """Handle margin changes."""
        self.plot_host.figure.subplots_adjust(
            left=margins["left"],
            right=margins["right"],
            top=margins["top"],
            bottom=margins["bottom"],
        )
        self.plot_host.canvas.draw_idle()

    def _on_export_requested(self, jobs: list) -> None:
        """Handle batch export request."""
        QMessageBox.information(
            self,
            "Export",
            f"Batch export of {len(jobs)} jobs will be implemented in Phase 4 (Batch Exporter).",
        )

    # ------------------------------------------------------------------ Event Handlers

    def closeEvent(self, event: QCloseEvent) -> None:
        """Handle window close event."""
        # Check for unsaved changes (future enhancement)
        self.studio_closed.emit()
        super().closeEvent(event)
