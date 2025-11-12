from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

from PyQt5.QtCore import QSize, Qt
from PyQt5.QtGui import QIcon, QKeySequence
from PyQt5.QtWidgets import QAction

from vasoanalyzer.ui.theme import CURRENT_THEME
from vasoanalyzer.ui.widgets import CustomToolbar

if TYPE_CHECKING:  # pragma: no cover
    from vasoanalyzer.ui.main_window import VasoAnalyzerApp


def build_canvas_toolbar(window: VasoAnalyzerApp, canvas: Any):
    """Construct the Matplotlib navigation toolbar with VasoAnalyzer styling."""

    # Detect backend type
    plot_host = getattr(window, "plot_host", None)
    is_pyqtgraph = (
        plot_host is not None
        and hasattr(plot_host, "get_render_backend")
        and plot_host.get_render_backend() == "pyqtgraph"
    )

    toolbar = CustomToolbar(canvas, window, reset_callback=window.reset_to_full_view)
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
            min-width: 52px;
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

    if hasattr(toolbar, "coordinates"):
        toolbar.coordinates = lambda *args, **kwargs: None
        for act in list(toolbar.actions()):
            if isinstance(act, QAction) and act.text() == "":
                toolbar.removeAction(act)

    base_actions = getattr(toolbar, "_actions", {})
    home_act = base_actions.get("home")
    back_act = base_actions.get("back")
    forward_act = base_actions.get("forward")
    pan_act = base_actions.get("pan")
    zoom_act = base_actions.get("zoom")
    subplots_act = base_actions.get("subplots")
    save_act = base_actions.get("save")

    for action in list(toolbar.actions()):
        toolbar.removeAction(action)

    if home_act:
        home_act.setText("Reset view")
        home_act.setShortcut(QKeySequence("R"))
        home_act.setToolTip(
            "<b>Reset View</b> <kbd>R</kbd><br><br>"
            "Resets plot to show entire trace.<br>"
            "Use to return to full time range."
        )
        home_act.setStatusTip("Reset the plot to the full time range.")
        home_act.setIcon(QIcon(window.icon_path("Home.svg")))

    if back_act:
        back_act.setText("Back")
        back_act.setToolTip(
            "<b>Back</b><br><br>"
            "Return to previous view in history.<br>"
            "Navigate backward through zoom history."
        )
        back_act.setIcon(QIcon(window.icon_path("Back.svg")))

    if forward_act:
        forward_act.setText("Forward")
        forward_act.setToolTip(
            "<b>Forward</b><br><br>"
            "Go to next view in history.<br>"
            "Navigate forward through zoom history."
        )
        forward_act.setIcon(QIcon(window.icon_path("Forward.svg")))

    if pan_act:
        pan_act.setText("Pan")
        pan_act.setToolTip(
            "<b>Pan</b> <kbd>P</kbd><br><br>"
            "Click and drag to move the view.<br>"
            "Press <kbd>Esc</kbd> to exit pan mode."
        )
        pan_act.setStatusTip("Drag to move the view. Press Esc to exit.")
        pan_act.setIcon(QIcon(window.icon_path("Pan.svg")))
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
        zoom_act.setIcon(QIcon(window.icon_path("Zoom.svg")))
        zoom_act.setShortcut(QKeySequence("Z"))
        zoom_act.setCheckable(True)

    if subplots_act:
        subplots_act.setVisible(False)

    if save_act:
        toolbar.removeAction(save_act)

    window.actReset = home_act
    window.actBack = back_act
    window.actForward = forward_act
    window.actPan = pan_act
    window.actZoom = zoom_act

    if window.actReset:
        toolbar.addAction(window.actReset)
    if window.actBack:
        toolbar.addAction(window.actBack)
    if window.actForward:
        toolbar.addAction(window.actForward)

    toolbar.addSeparator()

    # PyQtGraph has built-in mouse interaction - pan/zoom buttons not needed
    if not is_pyqtgraph:
        if window.actPan:
            toolbar.addAction(window.actPan)
        if window.actZoom:
            toolbar.addAction(window.actZoom)

        window._nav_mode_actions = [
            act for act in (window.actPan, window.actZoom) if act is not None
        ]
        for action in window._nav_mode_actions:
            with contextlib.suppress(Exception):
                action.toggled.disconnect(window._handle_nav_mode_toggled)
            action.toggled.connect(window._handle_nav_mode_toggled)

        toolbar.addSeparator()

    # Add zoom in/out/autoscale buttons for PyQtGraph
    if is_pyqtgraph:
        window.actZoomIn = QAction(QIcon(window.icon_path("Zoom.svg")), "Zoom In", window)
        window.actZoomIn.setShortcut(QKeySequence("+"))
        window.actZoomIn.setToolTip(
            "<b>Zoom In</b> <kbd>+</kbd><br><br>"
            "Zoom in to see more detail.<br>"
            "Increases magnification 2x."
        )
        window.actZoomIn.triggered.connect(window._on_zoom_in_triggered)
        toolbar.addAction(window.actZoomIn)

        window.actZoomOut = QAction(QIcon(window.icon_path("ZoomOut.svg")), "Zoom Out", window)
        window.actZoomOut.setShortcut(QKeySequence("-"))
        window.actZoomOut.setToolTip(
            "<b>Zoom Out</b> <kbd>-</kbd><br><br>"
            "Zoom out to see more time range.<br>"
            "Decreases magnification 2x."
        )
        window.actZoomOut.triggered.connect(window._on_zoom_out_triggered)
        toolbar.addAction(window.actZoomOut)

        window.actAutoscale = QAction(QIcon(window.icon_path("Home.svg")), "Autoscale", window)
        window.actAutoscale.setShortcut(QKeySequence("A"))
        window.actAutoscale.setToolTip(
            "<b>Autoscale</b> <kbd>A</kbd><br><br>"
            "Reset to full time range and autoscale Y axes.<br>"
            "Shows all data in view."
        )
        window.actAutoscale.triggered.connect(window._on_autoscale_triggered)
        toolbar.addAction(window.actAutoscale)

        toolbar.addSeparator()

        # Add Y-axis autoscale toggle
        window.actAutoscaleY = QAction(
            QIcon(window.icon_path("Grid.svg")), "Y-Axis Autoscale", window
        )
        window.actAutoscaleY.setCheckable(True)
        window.actAutoscaleY.setChecked(True)  # Enabled by default
        window.actAutoscaleY.setShortcut(QKeySequence("Y"))
        window.actAutoscaleY.setToolTip(
            "<b>Y-Axis Autoscale</b> <kbd>Y</kbd><br><br>"
            "Toggle Y-axis autoscaling.<br>"
            "When checked: Y-axis rescales as you pan.<br>"
            "When unchecked: Y-axis stays locked at current range."
        )
        window.actAutoscaleY.triggered.connect(window._on_autoscale_y_triggered)
        toolbar.addAction(window.actAutoscaleY)

        toolbar.addSeparator()

    window.actGrid = QAction(QIcon(window.icon_path("Grid.svg")), "Grid", window)
    window.actGrid.setCheckable(True)
    window.actGrid.setChecked(window.grid_visible)
    window.actGrid.setShortcut(QKeySequence("G"))
    window.actGrid.setToolTip(
        "<b>Toggle Grid</b> <kbd>G</kbd><br><br>"
        "Shows/hides coordinate grid overlay.<br>"
        "Use for precise alignment and measurements."
    )
    with contextlib.suppress(Exception):
        window.actGrid.triggered.disconnect(window._on_grid_action_triggered)
    window.actGrid.triggered.connect(window._on_grid_action_triggered)
    toolbar.addAction(window.actGrid)

    window.actStyle = QAction(QIcon(window.icon_path("plot-settings.svg")), "Style", window)
    if is_pyqtgraph:
        window.actStyle.setToolTip(
            "<b>Plot Settings</b><br><br>"
            "Open PyQtGraph plot settings dialog.<br>"
            "Customize tracks, event labels, and appearance."
        )
        with contextlib.suppress(Exception):
            window.actStyle.triggered.disconnect()
        window.actStyle.triggered.connect(lambda: window.open_pyqtgraph_settings_dialog())
    else:
        window.actStyle.setToolTip(
            "<b>Plot Settings</b><br><br>"
            "Open unified plot settings dialog.<br>"
            "Customize canvas, layout, axes, style, and event labels."
        )
        with contextlib.suppress(Exception):
            window.actStyle.triggered.disconnect()
        window.actStyle.triggered.connect(lambda: window.open_unified_plot_settings_dialog("style"))
    toolbar.addAction(window.actStyle)

    window.actEditPoints = QAction(
        QIcon(window.icon_path("tour-pencil.svg")),
        "Edit Points",
        window,
    )
    window.actEditPoints.setToolTip(
        "<b>Edit Points</b><br><br>"
        "Opens the Point Editor for manual trace correction.<br>"
        "Edit raw data points in the current view."
    )
    window.actEditPoints.setEnabled(False)
    window.actEditPoints.triggered.connect(window._on_edit_points_triggered)
    toolbar.addAction(window.actEditPoints)

    window._ensure_event_label_actions()
    window._sync_event_controls()
    window._sync_grid_action()
    window._update_trace_controls_state()

    return toolbar
