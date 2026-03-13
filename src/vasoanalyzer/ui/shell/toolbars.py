from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QIcon, QKeySequence, QAction, QActionGroup
from PyQt6.QtWidgets import QMenu, QToolButton

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
    toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
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

    _add_shared_plot_actions(window, toolbar, is_pyqtgraph=is_pyqtgraph, add_to_toolbar=False)
    _add_navigation_actions(window, toolbar, is_pyqtgraph=is_pyqtgraph)
    _add_view_toolbar_buttons(window, toolbar, is_pyqtgraph=is_pyqtgraph)
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
            log.debug("Failed to apply theme to toolbar", exc_info=True)

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
        home_act.setText("Fit View")
        home_act.setShortcut(QKeySequence("R"))
        home_act.setToolTip(
            "<b>Fit View</b> <kbd>R</kbd><br><br>"
            "Fit the plot to show the entire trace.<br>"
            "Use to return to the full time range."
        )
        home_act.setStatusTip("Fit view to the full time range.")
        home_act.setIcon(QIcon(window.icon_path("fit-view.svg")))

    if back_act:
        back_act.setText("Undo Zoom")
        back_act.setToolTip(
            "<b>Undo Zoom</b><br><br>"
            "Step back through zoom history.<br>"
            "Returns to the previous view state."
        )
        back_act.setIcon(QIcon(window.icon_path("undo-zoom.svg")))

    if forward_act:
        forward_act.setText("Redo Zoom")
        forward_act.setToolTip(
            "<b>Redo Zoom</b><br><br>"
            "Go to next view in history.<br>"
            "Navigate forward through zoom history."
        )
        forward_act.setIcon(QIcon(window.icon_path("Forward.svg")))

    if pan_act:
        pan_act.setText("Pan")
        pan_act.setToolTip("Pan: drag to move the view")
        pan_act.setStatusTip("Drag to move the view. Press Esc to exit.")
        pan_act.setIcon(QIcon(window.icon_path("Pan.svg")))
        pan_act.setShortcut(QKeySequence("P"))
        pan_act.setCheckable(True)

    if zoom_act:
        zoom_act.setText("Select")
        zoom_act.setToolTip("Select: drag to zoom into a region")
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
    window.actZoomBack = back_act

    if window.actPan:
        toolbar.addAction(window.actPan)
    if window.actZoom:
        toolbar.addAction(window.actZoom)

    window._nav_mode_actions = [act for act in (window.actPan, window.actZoom) if act is not None]
    for action in window._nav_mode_actions:
        with contextlib.suppress(Exception):
            action.toggled.disconnect(window._handle_nav_mode_toggled)
        action.toggled.connect(window._handle_nav_mode_toggled)


def _build_pyqtgraph_plot_toolbar(
    window: VasoAnalyzerApp, plot_host: Any, toolbar: CustomToolbar
) -> None:
    """Populate toolbar with PyQtGraph-native navigation actions."""

    window.actPgPan = QAction(QIcon(window.icon_path("Pan.svg")), "Pan", window)
    window.actPgPan.setCheckable(True)
    window.actPgPan.setShortcut(QKeySequence("P"))
    window.actPgPan.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
    window.actPgPan.setToolTip("Pan: drag to move the view")

    mouse_mode = "pan"
    if plot_host is not None and hasattr(plot_host, "mouse_mode"):
        with contextlib.suppress(Exception):
            mouse_mode = str(plot_host.mouse_mode()).lower()
    pan_checked = mouse_mode != "rect"
    window.actPgPan.setChecked(pan_checked)
    window.actPgPan.toggled.connect(window._on_pan_mode_toggled)
    window.actPgPan.toggled.connect(window._handle_nav_mode_toggled)
    toolbar.addAction(window.actPgPan)

    window.actBoxZoom = QAction(QIcon(window.icon_path("Zoom.svg")), "Select", window)
    window.actBoxZoom.setCheckable(True)
    window.actBoxZoom.setShortcut(QKeySequence("Z"))
    window.actBoxZoom.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
    window.actBoxZoom.setToolTip("Select: drag to zoom into a region")
    window.actBoxZoom.setChecked(not pan_checked)
    window.actBoxZoom.toggled.connect(window._on_box_zoom_toggled)
    window.actBoxZoom.toggled.connect(window._handle_nav_mode_toggled)
    toolbar.addAction(window.actBoxZoom)

    window._nav_mode_actions = [window.actPgPan, window.actBoxZoom]

    window.actZoomIn = QAction(QIcon(window.icon_path("Zoom.svg")), "Zoom In", window)
    window.actZoomIn.setShortcuts([QKeySequence("+"), QKeySequence("=")])
    window.actZoomIn.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
    window.actZoomIn.setToolTip(
        "<b>Zoom In</b> <kbd>+</kbd><br><br>"
        "Zoom in to see more detail along time.<br>"
        "Increases magnification along X."
    )
    window.actZoomIn.triggered.connect(window._on_zoom_in_triggered)

    window.actZoomOut = QAction(QIcon(window.icon_path("ZoomOut.svg")), "Zoom Out", window)
    window.actZoomOut.setShortcut(QKeySequence("-"))
    window.actZoomOut.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
    window.actZoomOut.setToolTip(
        "<b>Zoom Out</b> <kbd>-</kbd><br><br>"
        "Zoom out to see more time range.<br>"
        "Decreases magnification along X."
    )
    window.actZoomOut.triggered.connect(window._on_zoom_out_triggered)

    window.actZoomBack = QAction(QIcon(window.icon_path("undo-zoom.svg")), "Undo Zoom", window)
    window.actZoomBack.setShortcut(QKeySequence("Backspace"))
    window.actZoomBack.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
    window.actZoomBack.setToolTip(
        "<b>Undo Zoom</b> <kbd>Backspace</kbd><br><br>"
        "Step back through zoom history.<br>"
        "Returns to the previous view state."
    )
    window.actZoomBack.triggered.connect(window._on_zoom_back_triggered)

    window.actAutoscale = QAction(
        QIcon(window.icon_path("autoscale.svg")), "Autoscale Y", window
    )
    window.actAutoscale.setShortcut(QKeySequence("A"))
    window.actAutoscale.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
    window.actAutoscale.setToolTip(
        "<b>Autoscale Y</b> <kbd>A</kbd><br><br>"
        "Autoscale Y axis to the current time window.<br>"
        "Runs once; does not enable continuous autoscaling."
    )
    window.actAutoscale.triggered.connect(window._on_autoscale_triggered)

    window.actAutoscaleY = QAction(
        QIcon(window.icon_path("y-autoscale.svg")), "Y-Axis Autoscale", window
    )
    window.actAutoscaleY.setCheckable(True)
    window.actAutoscaleY.setShortcut(QKeySequence("Shift+A"))
    window.actAutoscaleY.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
    window.actAutoscaleY.setToolTip(
        "<b>Y-Axis Autoscale</b> <kbd>Shift+A</kbd><br><br>"
        "Toggle Y-axis autoscaling.<br>"
        "When checked: Y-axis rescales as you pan.<br>"
        "When unchecked: Y-axis stays locked at current range."
    )
    window.actAutoscaleY.triggered.connect(window._on_autoscale_y_triggered)
    window._sync_autoscale_y_action_from_host()


def _add_shared_plot_actions(
    window: VasoAnalyzerApp,
    toolbar: CustomToolbar,
    *,
    is_pyqtgraph: bool,
    add_to_toolbar: bool = True,
) -> None:
    """Add actions common to both backends."""

    window.actGrid = QAction(QIcon(window.icon_path("Grid.svg")), "Grid", window)
    window.actGrid.setCheckable(True)
    window.actGrid.setChecked(window.grid_visible)
    window.actGrid.setShortcut(QKeySequence("G"))
    window.actGrid.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
    window.actGrid.setToolTip(
        "<b>Toggle Grid</b> <kbd>G</kbd><br><br>"
        "Shows/hides coordinate grid overlay.<br>"
        "Use for precise alignment and measurements."
    )
    with contextlib.suppress(Exception):
        window.actGrid.triggered.disconnect(window._on_grid_action_triggered)
    window.actGrid.triggered.connect(window._on_grid_action_triggered)
    if add_to_toolbar:
        toolbar.addAction(window.actGrid)

    window.actOverviewStrip = QAction("Overview strip", window)
    window.actOverviewStrip.setCheckable(True)
    window.actOverviewStrip.setChecked(getattr(window, "_overview_strip_enabled", False))
    window.actOverviewStrip.setToolTip("Show or hide the overview strip")
    with contextlib.suppress(Exception):
        window.actOverviewStrip.triggered.disconnect()
    window.actOverviewStrip.triggered.connect(window.toggle_overview_strip)

    if is_pyqtgraph:
        window.actChannelEventLabels = QAction(QIcon(window.icon_path("event-label.svg")), "Event Labels", window)
        window.actChannelEventLabels.setCheckable(True)
        window.actChannelEventLabels.setChecked(
            getattr(window, "_channel_event_labels_visible", False)
        )
        window.actChannelEventLabels.setToolTip(
            "<b>Event Labels</b><br><br>"
            "Show vertical event text labels next to each<br>"
            "dashed marker line inside channel tracks."
        )
        with contextlib.suppress(Exception):
            window.actChannelEventLabels.triggered.disconnect()
        window.actChannelEventLabels.triggered.connect(window.toggle_channel_event_labels)

        # Font-size submenu for event labels.
        size_menu = QMenu("Event label size", None)
        size_group = QActionGroup(size_menu)
        size_group.setExclusive(True)
        current_size = float(getattr(window, "_channel_event_label_font_size", 9.0))
        for label, pt in (("Small (7 pt)", 7.0), ("Medium (9 pt)", 9.0),
                          ("Large (11 pt)", 11.0), ("Extra Large (14 pt)", 14.0)):
            act = QAction(label, size_menu)
            act.setCheckable(True)
            act.setData(pt)
            act.setChecked(pt == current_size)
            size_group.addAction(act)
            size_menu.addAction(act)
            with contextlib.suppress(Exception):
                act.triggered.connect(
                    lambda _checked, _pt=pt: window.set_channel_event_label_font_size(_pt)
                )
        window._event_label_size_menu = size_menu
        window._event_label_font_size_group = size_group

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
    if add_to_toolbar:
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
    if add_to_toolbar:
        toolbar.addAction(window.actEditPoints)


def _ensure_zoom_all_action(window: VasoAnalyzerApp) -> QAction:
    zoom_all = getattr(window, "actZoomAllX", None)
    if zoom_all is None:
        zoom_all = QAction(QIcon(window.icon_path("Home.svg")), "Fit View", window)
        zoom_all.triggered.connect(window._zoom_all_x)
        window.actZoomAllX = zoom_all
    zoom_all.setText("Fit View")
    zoom_all.setToolTip(
        "<b>Fit View</b> <kbd>R</kbd><br><br>"
        "Fit the plot to show the entire trace.<br>"
        "Use to return to the full time range."
    )
    zoom_all.setIcon(QIcon(window.icon_path("fit-view.svg")))
    return zoom_all


def _ensure_time_preset_actions(window: VasoAnalyzerApp) -> list[QAction]:
    presets = [
        ("actTimePreset1s", "Window 1s", 1.0, "Set view to 1 second"),
        ("actTimePreset10s", "Window 10s", 10.0, "Set view to 10 seconds"),
        ("actTimePreset60s", "Window 60s", 60.0, "Set view to 60 seconds"),
    ]
    actions: list[QAction] = []
    for attr_name, label, span, tooltip in presets:
        action = getattr(window, attr_name, None)
        if action is None:
            action = QAction(label, window)
            action.setToolTip(tooltip)
            action.triggered.connect(
                lambda _checked=False, s=span: window._apply_time_span_preset(s)
            )
            setattr(window, attr_name, action)
        actions.append(action)
    return actions


def _add_navigation_actions(
    window: VasoAnalyzerApp, toolbar: CustomToolbar, *, is_pyqtgraph: bool
) -> set[QAction]:
    """Add Navigation group quick-access buttons in order:
    Fit View, Autoscale Y, Zoom In, Zoom Out, Undo Zoom."""

    promoted: set[QAction] = set()

    def add_button(
        action: QAction | None,
        tooltip: str,
        attr_name: str,
        object_name: str,
    ) -> None:
        if action is None:
            return
        button = QToolButton(toolbar)
        button.setObjectName(object_name)
        button.setDefaultAction(action)
        button.setToolTip(tooltip)
        button.setIconSize(toolbar.iconSize())
        button.setToolButtonStyle(toolbar.toolButtonStyle())
        action_widget = toolbar.addWidget(button)
        setattr(toolbar, attr_name, action_widget)
        promoted.add(action)

    zoom_all = _ensure_zoom_all_action(window)
    add_button(
        zoom_all,
        "Fit view to full time range",
        "_quick_zoom_all_action",
        "PlotToolbarZoomAll",
    )
    add_button(
        getattr(window, "actAutoscale", None),
        "Autoscale Y once (does not stay on)",
        "_quick_autoscale_action",
        "PlotToolbarAutoscale",
    )
    add_button(
        getattr(window, "actZoomIn", None),
        "Zoom in (time axis)",
        "_quick_zoom_in_action",
        "PlotToolbarZoomIn",
    )
    add_button(
        getattr(window, "actZoomOut", None),
        "Zoom out (time axis)",
        "_quick_zoom_out_action",
        "PlotToolbarZoomOut",
    )
    add_button(
        getattr(window, "actZoomBack", None),
        "Undo last zoom",
        "_quick_zoom_back_action",
        "PlotToolbarZoomBack",
    )

    return promoted


def _add_view_toolbar_buttons(
    window: VasoAnalyzerApp,
    toolbar: CustomToolbar,
    *,
    is_pyqtgraph: bool,
) -> None:
    """Add View group buttons directly to the toolbar: Grid, Event Labels, Style."""

    toolbar.addSeparator()

    act_grid = getattr(window, "actGrid", None)
    if act_grid is not None:
        toolbar.addAction(act_grid)

    if is_pyqtgraph:
        act_labels = getattr(window, "actChannelEventLabels", None)
        if act_labels is not None:
            size_menu = getattr(window, "_event_label_size_menu", None)
            if size_menu is not None:
                btn = QToolButton(toolbar)
                btn.setObjectName("PlotToolbarEventLabels")
                btn.setDefaultAction(act_labels)
                btn.setIconSize(toolbar.iconSize())
                btn.setToolButtonStyle(toolbar.toolButtonStyle())
                btn.setMenu(size_menu)
                btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
                toolbar._event_labels_widget_action = toolbar.addWidget(btn)
            else:
                toolbar.addAction(act_labels)

    act_style = getattr(window, "actStyle", None)
    if act_style is not None:
        toolbar.addAction(act_style)


def _apply_toolbar_styles(toolbar: CustomToolbar) -> None:
    """Apply stylesheet to the plot toolbar based on CURRENT_THEME."""

    border_color = CURRENT_THEME.get("panel_border", CURRENT_THEME["grid_color"])
    separator_color = CURRENT_THEME.get("grid_color", border_color)
    bg = CURRENT_THEME.get("toolbar_bg", CURRENT_THEME.get("window_bg", "#FFFFFF"))
    button_bg = CURRENT_THEME.get("button_bg", bg)
    hover_bg = CURRENT_THEME.get("button_hover_bg", CURRENT_THEME.get("selection_bg", bg))
    checked_bg = CURRENT_THEME.get("selection_bg", hover_bg)
    pressed_bg = CURRENT_THEME.get("button_active_bg", checked_bg)
    checked_border = CURRENT_THEME.get("accent", border_color)
    text_color = CURRENT_THEME["text"]
    disabled_text = CURRENT_THEME.get("text_disabled", text_color)
    radius = int(CURRENT_THEME.get("panel_radius", 4))
    toolbar.setStyleSheet(
        f"""
        QToolBar#PlotToolbar {{
            background: {bg};
            border: 1px solid {border_color};
            border-radius: {radius}px;
            padding: 3px 4px;
            spacing: 3px;
        }}
        QToolBar#PlotToolbar::separator {{
            background: {border_color};
            width: 2px;
            border-radius: 1px;
            margin: 3px 8px;
        }}
        QToolBar#PlotToolbar QToolButton {{
            background: {button_bg};
            border: 1px solid {border_color};
            border-radius: {radius}px;
            margin: 1px 2px;
            padding: 4px 7px;
            min-width: 44px;
            color: {text_color};
        }}
        QToolBar#PlotToolbar QToolButton:disabled {{
            background: {bg};
            border: 1px solid {separator_color};
            color: {disabled_text};
        }}
        QToolBar#PlotToolbar QToolButton:hover {{
            background: {hover_bg};
        }}
        QToolBar#PlotToolbar QToolButton:checked {{
            background: {checked_bg};
            border: 1px solid {checked_border};
            color: {text_color};
        }}
        QToolBar#PlotToolbar QToolButton:checked:hover {{
            background: {checked_bg};
            border: 1px solid {checked_border};
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
        base_actions.get("home"): "fit-view.svg",
        base_actions.get("back"): "undo-zoom.svg",
        base_actions.get("forward"): "Forward.svg",
        base_actions.get("pan"): "Pan.svg",
        base_actions.get("zoom"): "Zoom.svg",
        base_actions.get("save"): None,
    }
    extras = {
        getattr(window, "actZoomIn", None): "Zoom.svg",
        getattr(window, "actZoomOut", None): "ZoomOut.svg",
        getattr(window, "actZoomBack", None): "undo-zoom.svg",
        getattr(window, "actZoomAllX", None): "fit-view.svg",
        getattr(window, "actAutoscale", None): "autoscale.svg",
        getattr(window, "actAutoscaleY", None): "y-autoscale.svg",
        getattr(window, "actPgPan", None): "Pan.svg",
        getattr(window, "actBoxZoom", None): "Zoom.svg",
        getattr(window, "actGrid", None): "Grid.svg",
        getattr(window, "actChannelEventLabels", None): "event-label.svg",
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
