from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

from PyQt5.QtCore import QSize, Qt
from PyQt5.QtGui import QIcon, QKeySequence
from PyQt5.QtWidgets import QAction, QMenu, QToolButton

from vasoanalyzer.ui.theme import CURRENT_THEME
from vasoanalyzer.ui.widgets import CustomToolbar

if TYPE_CHECKING:  # pragma: no cover
    from vasoanalyzer.ui.main_window import VasoAnalyzerApp


def build_canvas_toolbar(window: VasoAnalyzerApp, canvas: Any):
    """Construct the Matplotlib navigation toolbar with VasoAnalyzer styling."""

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
        home_act.setToolTip("Reset view (R) — show entire trace")
        home_act.setStatusTip("Reset the plot to the full time range.")
        home_act.setIcon(QIcon(window.icon_path("Home.svg")))

    if back_act:
        back_act.setText("Back")
        back_act.setToolTip("Back — previous view")
        back_act.setIcon(QIcon(window.icon_path("Back.svg")))

    if forward_act:
        forward_act.setText("Forward")
        forward_act.setToolTip("Forward — next view")
        forward_act.setIcon(QIcon(window.icon_path("Forward.svg")))

    if pan_act:
        pan_act.setText("Pan")
        pan_act.setToolTip("Pan (P) — drag to move")
        pan_act.setStatusTip("Drag to move the view. Press Esc to exit.")
        pan_act.setIcon(QIcon(window.icon_path("Pan.svg")))
        pan_act.setShortcut(QKeySequence("P"))
        pan_act.setCheckable(True)

    if zoom_act:
        zoom_act.setText("Zoom")
        zoom_act.setToolTip("Zoom (Z) — draw a box to zoom")
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

    if window.actPan:
        toolbar.addAction(window.actPan)
    if window.actZoom:
        toolbar.addAction(window.actZoom)

    window._nav_mode_actions = [act for act in (window.actPan, window.actZoom) if act is not None]
    for action in window._nav_mode_actions:
        with contextlib.suppress(Exception):
            action.toggled.disconnect(window._handle_nav_mode_toggled)
        action.toggled.connect(window._handle_nav_mode_toggled)

    toolbar.addSeparator()

    window.actGrid = QAction(QIcon(window.icon_path("Grid.svg")), "Grid", window)
    window.actGrid.setCheckable(True)
    window.actGrid.setChecked(window.grid_visible)
    window.actGrid.setShortcut(QKeySequence("G"))
    window.actGrid.setToolTip("Toggle grid (G)")
    with contextlib.suppress(Exception):
        window.actGrid.triggered.disconnect(window._on_grid_action_triggered)
    window.actGrid.triggered.connect(window._on_grid_action_triggered)
    toolbar.addAction(window.actGrid)

    window.actStyle = QAction(QIcon(window.icon_path("plot-settings.svg")), "Style", window)
    window.actStyle.setToolTip("Open plot style settings")
    with contextlib.suppress(Exception):
        window.actStyle.triggered.disconnect()
    window.actStyle.triggered.connect(lambda: window.open_unified_plot_settings_dialog("style"))
    toolbar.addAction(window.actStyle)

    window.actEditPoints = QAction(
        QIcon(window.icon_path("tour-pencil.svg")),
        "Edit Points",
        window,
    )
    window.actEditPoints.setToolTip("Edit raw points in the current view (opens the Point Editor)")
    window.actEditPoints.setEnabled(False)
    window.actEditPoints.triggered.connect(window._on_edit_points_triggered)
    toolbar.addAction(window.actEditPoints)

    window._ensure_event_label_actions()
    label_menu = QMenu(window)
    label_menu.addAction(window.actEventLabelsVertical)
    label_menu.addAction(window.actEventLabelsHorizontal)
    label_menu.addAction(window.actEventLabelsOutside)
    window._toolbar_event_label_menu = label_menu

    window.event_label_button = QToolButton()
    window.event_label_button.setToolTip("Select event label mode")
    window.event_label_button.setPopupMode(QToolButton.InstantPopup)
    window.event_label_button.setMenu(label_menu)
    toolbar.addWidget(window.event_label_button)

    window._sync_event_controls()
    window._sync_grid_action()
    window._update_trace_controls_state()

    return toolbar
