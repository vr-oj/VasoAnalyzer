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
    QUndoCommand,
    QUndoStack,
    QVBoxLayout,
    QWidget,
)

from vasoanalyzer.core.trace_model import TraceModel
from vasoanalyzer.ui.builtin_presets import get_builtin_presets
from vasoanalyzer.ui.docks.advanced_style_dock import AdvancedStyleDock
from vasoanalyzer.ui.docks.export_queue_dock import ExportQueueDock, ExportStatus
from vasoanalyzer.ui.docks.layout_dock import LayoutDock
from vasoanalyzer.ui.docks.preset_library_dock import PresetLibraryDock
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
            self.studio.plot_host.canvas.draw_idle()
            # Update style dock
            if hasattr(self.studio, "_advanced_style_dock"):
                self.studio._advanced_style_dock.set_style(self.new_style)

    def undo(self) -> None:
        """Revert to old style."""
        if self.studio._style_manager:
            self.studio._style_manager.replace(self.old_style)
            self.studio._current_preset_name = None  # Custom style, no preset
            self.studio._apply_style_to_plot()
            self.studio.plot_host.canvas.draw_idle()
            # Update style dock
            if hasattr(self.studio, "_advanced_style_dock"):
                self.studio._advanced_style_dock.set_style(self.old_style)


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

        # Epoch overlay state
        self._epochs: list[Epoch] = []
        self._epoch_layer: EpochLayer | None = None
        self._epoch_theme: EpochTheme = EpochTheme()
        self._epochs_visible: bool = True

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

    def get_current_style(self) -> dict[str, Any]:
        """Snapshot current plot style from PlotHost artists."""
        if self._style_manager:
            return cast(dict[str, Any], self._style_manager.style())
        return {}

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
        if self._layout_state and hasattr(self, "_layout_dock"):
            # Note: PlotHost doesn't have set_layout_state, layout is applied via channel specs
            # Update layout dock
            self._layout_dock.set_layout_state(self._layout_state)

        # Apply initial style
        if self._style_manager:
            self._apply_style_to_plot()
            # Update style dock with flat style
            if hasattr(self, "_advanced_style_dock"):
                self._advanced_style_dock.set_style(self._style_manager.style())

        # Refresh canvas
        self.plot_host.canvas.draw_idle()

    def _apply_style_to_plot(self) -> None:
        """Apply current style manager settings to PlotHost."""
        if not self._style_manager:
            return

        # Apply style to all channel tracks in PlotHost
        for track in self.plot_host._tracks.values():
            if not track.ax:
                continue

            # Get track's axes
            ax = track.ax
            ax_secondary = track.ax_secondary if hasattr(track, "ax_secondary") else None

            # Get main and OD lines if they exist
            main_line = track.inner_line if hasattr(track, "inner_line") else None
            od_line = track.outer_line if hasattr(track, "outer_line") else None

            # Apply style to this track
            self._style_manager.apply(
                ax=ax,
                ax_secondary=ax_secondary,
                x_axis=None,  # Use the track's own x-axis
                event_text_objects=None,  # Events handled separately
                pinned_points=None,  # Pinned points handled separately
                main_line=main_line,
                od_line=od_line,
            )

        # Apply style to event labeler if present
        if (
            hasattr(self.plot_host, "_event_helper_v3")
            and self.plot_host._event_helper_v3
            and hasattr(self.plot_host, "_refresh_event_labels_v3")
        ):
            # Event labels will pick up the style from the updated axes
            # Force refresh of event labels
            self.plot_host._refresh_event_labels_v3()

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
        """Save current style as preset via the preset library dock.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
        # Trigger the preset library dock's save button
        if hasattr(self, "_preset_library_dock"):
            self._preset_library_dock._on_save_clicked()
        else:
            QMessageBox.warning(
                self,
                "Preset Library Unavailable",
                "Preset library dock is not available. Please use the dock panel to save presets.",
            )

    def _on_load_preset(self, checked: bool = False) -> None:
        """Load a preset via the preset library dock.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
        # Show message directing to preset library
        QMessageBox.information(
            self,
            "Load Preset",
            "Please use the Preset Library dock (left panel) to browse and load presets.\n\n"
            "You can double-click a preset to apply it, or select it and click 'Load'.",
        )

    def _on_about(self, checked: bool = False) -> None:
        """Show about dialog.

        Args:
            checked: Unused boolean from Qt signal (ignored)
        """
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

    # ------------------------------------------------------------------ Dock Signal Handlers

    def _on_preset_load_requested(self, preset: dict[str, Any]) -> None:
        """Handle preset load request."""
        self.apply_preset(preset)

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
        """Apply current style to plot with undo support."""
        if not self._style_manager:
            return

        # Get current and new styles for undo
        old_style = self._style_manager.style()
        new_style = (
            self._advanced_style_dock.get_style()
            if hasattr(self, "_advanced_style_dock")
            else old_style
        )

        # Create undo command
        command = StyleChangeCommand(self, old_style, new_style, "Apply Style")
        self.undo_stack.push(command)

    def _on_style_revert(self) -> None:
        """Revert to previous style using undo stack."""
        if self.undo_stack.canUndo():
            self.undo_stack.undo()
        else:
            QMessageBox.information(
                self, "Nothing to Revert", "No previous style changes to revert."
            )

    def _on_layout_changed(self, layout_state: LayoutState) -> None:
        """Handle layout change from LayoutDock."""
        # Update channel visibility and height ratios
        for track_id, visible in layout_state.visibility.items():
            if track_id in self.plot_host._tracks:
                track = self.plot_host._tracks[track_id]
                if hasattr(track, "set_visible"):
                    track.set_visible(visible)
                elif track.ax:
                    track.ax.set_visible(visible)

        # Update height ratios by modifying channel specs
        for i, spec in enumerate(self._channel_specs):
            if spec.track_id in layout_state.height_ratios:
                new_ratio = layout_state.height_ratios[spec.track_id]
                self._channel_specs[i] = ChannelTrackSpec(
                    track_id=spec.track_id,
                    label=spec.label,
                    component=spec.component,
                    height_ratio=new_ratio,
                )

        # Re-apply layout by recreating the plot structure
        # This is a simplified approach - a full implementation would need
        # to update GridSpec parameters dynamically
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
        import json
        from pathlib import Path

        if not jobs:
            QMessageBox.warning(self, "No Jobs", "No jobs to export.")
            return

        from PyQt5.QtCore import QTimer

        # Process export jobs
        successful = 0
        failed = 0

        for job in jobs:
            try:
                # Apply preset if specified
                if job.preset_name and hasattr(self, "_preset_library_dock"):
                    # Find and apply preset
                    all_presets = (
                        self._preset_library_dock._presets
                        + self._preset_library_dock._built_in_presets
                    )
                    preset = next(
                        (p for p in all_presets if p.get("name") == job.preset_name), None
                    )
                    if preset:
                        self.apply_preset(preset)

                # Set figure size (convert mm to inches: 1 inch = 25.4 mm)
                width_inches = job.width_mm / 25.4
                height_inches = job.height_mm / 25.4
                self.plot_host.figure.set_size_inches(width_inches, height_inches)

                # Export with specified settings
                self.plot_host.figure.savefig(
                    job.output_path,
                    dpi=job.dpi,
                    format=job.format.lower(),
                    bbox_inches="tight",
                    pad_inches=0.1,
                )

                # Save epoch metadata as sidecar JSON if epochs exist
                if self._epochs and self._epoch_layer is not None:
                    manifest = self._epoch_layer.to_manifest()
                    metadata_path = Path(job.output_path).with_suffix(".epochs.json")
                    with open(metadata_path, "w") as f:
                        json.dump(manifest, f, indent=2)

                # Update job status
                if hasattr(self, "_export_queue_dock"):
                    self._export_queue_dock.update_job_status(job.name, ExportStatus.COMPLETED)
                successful += 1

            except Exception as e:
                if hasattr(self, "_export_queue_dock"):
                    self._export_queue_dock.update_job_status(job.name, ExportStatus.FAILED, str(e))
                failed += 1

        # Show summary
        QMessageBox.information(
            self,
            "Batch Export Complete",
            f"Export completed:\n"
            f"✓ {successful} successful\n"
            f"✗ {failed} failed\n\n"
            f"Check the Export Queue for details.",
        )

    # ------------------------------------------------------------------ Event Handlers

    def closeEvent(self, event: QCloseEvent) -> None:
        """Handle window close event."""
        # Check for unsaved changes (future enhancement)
        self.studio_closed.emit()
        super().closeEvent(event)
