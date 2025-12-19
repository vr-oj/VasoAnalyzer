from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING, Any

from PyQt5.QtCore import QSize, Qt
from PyQt5.QtGui import QIcon, QKeySequence
from PyQt5.QtWidgets import QAction

from vasoanalyzer.ui.theme import CURRENT_THEME
from vasoanalyzer.ui.widgets import CustomToolbar

if TYPE_CHECKING:  # pragma: no cover
    from vasoanalyzer.ui.main_window import VasoAnalyzerApp

log = logging.getLogger(__name__)


def build_canvas_toolbar(window: VasoAnalyzerApp, canvas: Any):
    """Construct the plot toolbar with backend-specific controls."""

    plot_host = getattr(window, "plot_host", None)
    return build_plot_toolbar(window, canvas, plot_host)


def build_plot_toolbar(window: VasoAnalyzerApp, canvas: Any, plot_host: Any):
    """Backend-aware toolbar entry point."""

    is_pyqtgraph = (
        plot_host is not None
        and hasattr(plot_host, "get_render_backend")
        and plot_host.get_render_backend() == "pyqtgraph"
    )

    toolbar = CustomToolbar(canvas, window, reset_callback=window.reset_to_full_view)
    toolbar.setObjectName("PlotToolbar")
    toolbar.setIconSize(QSize(22, 22))
    toolbar.setContentsMargins(0, 0, 0, 0)
    toolbar.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
    toolbar.setFloatable(False)
    toolbar.setMovable(False)
    _apply_toolbar_styles(toolbar)

    if hasattr(toolbar, "coordinates"):
        toolbar.coordinates = lambda *args, **kwargs: None
        for act in list(toolbar.actions()):
            if isinstance(act, QAction) and act.text() == "":
                toolbar.removeAction(act)

    for action in list(toolbar.actions()):
        toolbar.removeAction(action)

    if is_pyqtgraph:
        _build_pyqtgraph_plot_toolbar(window, plot_host, toolbar)
    else:
        _build_matplotlib_plot_toolbar(window, canvas, plot_host, toolbar)

    _add_shared_plot_actions(window, toolbar, is_pyqtgraph=is_pyqtgraph)
    window._ensure_event_label_actions()
    window._sync_event_controls()
    window._sync_grid_action()
    window._update_trace_controls_state()

    def apply_theme() -> None:
        log.debug("[THEME-DEBUG] PlotToolbar.apply_theme called, id(self)=%s", id(toolbar))
        _apply_toolbar_styles(toolbar)
        _reassign_toolbar_icons(toolbar, window)
        try:
            from .. import theme as theme_module

            toolbar_bg = (
                theme_module.CURRENT_THEME.get("toolbar_bg")
                if isinstance(theme_module.CURRENT_THEME, dict)
                else None
            )
            log.debug("[THEME-DEBUG] PlotToolbar theme toolbar_bg=%r", toolbar_bg)
        except Exception:
            pass

    toolbar.apply_theme = apply_theme

    return toolbar


def _build_matplotlib_plot_toolbar(
    window: VasoAnalyzerApp, canvas: Any, plot_host: Any, toolbar: CustomToolbar
) -> None:
    """Populate toolbar with Matplotlib-native navigation actions."""

    base_actions = getattr(toolbar, "_actions", {})
    home_act = base_actions.get("home")
    back_act = base_actions.get("back")
    forward_act = base_actions.get("forward")
    pan_act = base_actions.get("pan")
    zoom_act = base_actions.get("zoom")
    subplots_act = base_actions.get("subplots")

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


def _build_pyqtgraph_plot_toolbar(
    window: VasoAnalyzerApp, plot_host: Any, toolbar: CustomToolbar
) -> None:
    """Populate toolbar with PyQtGraph-native navigation actions."""

    window.actPgPan = QAction(QIcon(window.icon_path("Pan.svg")), "Pan", window)
    window.actPgPan.setCheckable(True)
    window.actPgPan.setShortcut(QKeySequence("P"))
    window.actPgPan.setToolTip(
        "<b>Pan</b> <kbd>P</kbd><br><br>"
        "Drag to move the view along time.<br>"
        "PyQtGraph native pan mode."
    )

    mouse_mode = "pan"
    if plot_host is not None and hasattr(plot_host, "mouse_mode"):
        with contextlib.suppress(Exception):
            mouse_mode = str(plot_host.mouse_mode()).lower()
    pan_checked = mouse_mode != "rect"
    window.actPgPan.setChecked(pan_checked)
    window.actPgPan.toggled.connect(window._on_pan_mode_toggled)
    window.actPgPan.toggled.connect(window._handle_nav_mode_toggled)
    toolbar.addAction(window.actPgPan)

    window.actBoxZoom = QAction(QIcon(window.icon_path("Zoom.svg")), "Box Zoom", window)
    window.actBoxZoom.setCheckable(True)
    window.actBoxZoom.setShortcut(QKeySequence("Z"))
    window.actBoxZoom.setToolTip(
        "<b>Box Zoom</b> <kbd>Z</kbd><br><br>"
        "Drag a rectangle to zoom in along time.<br>"
        "Press <kbd>Esc</kbd> or toggle off to return to pan."
    )
    window.actBoxZoom.setChecked(not pan_checked)
    window.actBoxZoom.toggled.connect(window._on_box_zoom_toggled)
    window.actBoxZoom.toggled.connect(window._handle_nav_mode_toggled)
    toolbar.addAction(window.actBoxZoom)

    window._nav_mode_actions = [window.actPgPan, window.actBoxZoom]

    window.actZoomIn = QAction(QIcon(window.icon_path("Zoom.svg")), "Zoom In", window)
    window.actZoomIn.setShortcut(QKeySequence("+"))
    window.actZoomIn.setToolTip(
        "<b>Zoom In</b> <kbd>+</kbd><br><br>"
        "Zoom in to see more detail along time.<br>"
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

    window.actZoomBack = QAction(QIcon(window.icon_path("Back.svg")), "Zoom Back", window)
    window.actZoomBack.setShortcut(QKeySequence("Backspace"))
    window.actZoomBack.setToolTip(
        "<b>Zoom Back</b> <kbd>Backspace</kbd><br><br>"
        "Step back through zoom history.<br>"
        "Returns to previous view state."
    )
    window.actZoomBack.triggered.connect(window._on_zoom_back_triggered)
    toolbar.addAction(window.actZoomBack)

    window.actAutoscale = QAction(QIcon(window.icon_path("autoscale.svg")), "Autoscale", window)
    window.actAutoscale.setShortcut(QKeySequence("A"))
    window.actAutoscale.setToolTip(
        "<b>Autoscale</b> <kbd>A</kbd><br><br>"
        "Reset to full time range and autoscale Y axes.<br>"
        "Shows all data in view."
    )
    window.actAutoscale.triggered.connect(window._on_autoscale_triggered)
    toolbar.addAction(window.actAutoscale)

    window.actAutoscaleY = QAction(
        QIcon(window.icon_path("y-autoscale.svg")), "Y-Axis Autoscale", window
    )
    window.actAutoscaleY.setCheckable(True)
    window.actAutoscaleY.setShortcut(QKeySequence("Y"))
    window.actAutoscaleY.setToolTip(
        "<b>Y-Axis Autoscale</b> <kbd>Y</kbd><br><br>"
        "Toggle Y-axis autoscaling.<br>"
        "When checked: Y-axis rescales as you pan.<br>"
        "When unchecked: Y-axis stays locked at current range."
    )
    window.actAutoscaleY.triggered.connect(window._on_autoscale_y_triggered)
    window._sync_autoscale_y_action_from_host()
    toolbar.addAction(window.actAutoscaleY)

    toolbar.addSeparator()


def _add_shared_plot_actions(
    window: VasoAnalyzerApp, toolbar: CustomToolbar, *, is_pyqtgraph: bool
) -> None:
    """Add actions common to both backends."""

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
        "Edit data points in the current time window.<br>"
        "Opens a point editor dialog where you can click or box-select points.<br>"
        "Shift-click adds to selection; Ctrl/Cmd-click toggles. Changes apply when you press Apply."
    )
    window.actEditPoints.setEnabled(False)
    window.actEditPoints.triggered.connect(window._on_edit_points_triggered)
    toolbar.addAction(window.actEditPoints)


def _apply_toolbar_styles(toolbar: CustomToolbar) -> None:
    """Apply stylesheet to the plot toolbar based on CURRENT_THEME."""

    border_color = CURRENT_THEME["grid_color"]
    bg = CURRENT_THEME.get("toolbar_bg", CURRENT_THEME.get("window_bg", "#FFFFFF"))
    hover_bg = CURRENT_THEME.get("button_hover_bg", CURRENT_THEME.get("selection_bg", bg))
    checked_bg = CURRENT_THEME.get("selection_bg", hover_bg)
    pressed_bg = CURRENT_THEME.get("button_active_bg", checked_bg)
    text_color = CURRENT_THEME["text"]
    disabled_text = CURRENT_THEME.get("text_disabled", text_color)
    toolbar.setStyleSheet(
        f"""
        QToolBar#PlotToolbar {{
            background: {bg};
            border: 1px solid {border_color};
            border-radius: 10px;
            padding: 4px 6px;
            spacing: 2px;
        }}
        QToolBar#PlotToolbar QToolButton {{
            background: transparent;
            border: none;
            border-radius: 10px;
            margin: 0px 3px;
            padding: 6px 10px;
            min-width: 54px;
            color: {text_color};
        }}
        QToolBar#PlotToolbar QToolButton:disabled {{
            color: {disabled_text};
        }}
        QToolBar#PlotToolbar QToolButton:hover {{
            background: {hover_bg};
        }}
        QToolBar#PlotToolbar QToolButton:checked {{
            background: {checked_bg};
            color: {text_color};
        }}
        QToolBar#PlotToolbar QToolButton:pressed {{
            background: {pressed_bg};
        }}
    """
    )


def _reassign_toolbar_icons(toolbar: CustomToolbar, window: VasoAnalyzerApp) -> None:
    """Refresh toolbar icons from the current theme-aware icon path."""

    base_actions = getattr(toolbar, "_actions", {})
    icon_map = {
        base_actions.get("home"): "Home.svg",
        base_actions.get("back"): "Back.svg",
        base_actions.get("forward"): "Forward.svg",
        base_actions.get("pan"): "Pan.svg",
        base_actions.get("zoom"): "Zoom.svg",
        base_actions.get("save"): None,
    }
    extras = {
        getattr(window, "actZoomIn", None): "Zoom.svg",
        getattr(window, "actZoomOut", None): "ZoomOut.svg",
        getattr(window, "actZoomBack", None): "Back.svg",
        getattr(window, "actAutoscale", None): "autoscale.svg",
        getattr(window, "actAutoscaleY", None): "y-autoscale.svg",
        getattr(window, "actPgPan", None): "Pan.svg",
        getattr(window, "actBoxZoom", None): "Zoom.svg",
        getattr(window, "actGrid", None): "Grid.svg",
        getattr(window, "actStyle", None): "plot-settings.svg",
        getattr(window, "actEditPoints", None): "tour-pencil.svg",
    }
    icon_map.update(extras)
    for action, icon_name in icon_map.items():
        if action is None or not icon_name:
            continue
        try:
            action.setIcon(QIcon(window.icon_path(icon_name)))
        except Exception:
            continue
