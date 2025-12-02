# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Menu-related functionality for VasoAnalyzer main window."""

import os
import sys
import webbrowser
from functools import partial

from PyQt5.QtGui import QIcon, QKeySequence
from PyQt5.QtWidgets import QAction, QMessageBox, QWidget


class MenuMixin:
    """Mixin class providing menu bar construction and management functionality."""

    def update_recent_files_menu(self):
        self.recent_menu.clear()

        if not self.recent_files:
            self.recent_menu.addAction("No recent files").setEnabled(False)
        else:
            for path in self.recent_files:
                action = QAction(os.path.basename(path), self)
                action.setToolTip(path)
                action.triggered.connect(partial(self.load_trace_and_events, path))
                self.recent_menu.addAction(action)

        self._refresh_home_recent()

    def _assign_menu_role(self, action, role_name):
        menu_role_enum = getattr(QAction, "MenuRole", None)
        menu_role = None
        if menu_role_enum is not None and hasattr(menu_role_enum, role_name):
            menu_role = getattr(menu_role_enum, role_name)
        elif hasattr(QAction, role_name):
            menu_role = getattr(QAction, role_name)
        if menu_role is not None:
            action.setMenuRole(menu_role)

    def create_menubar(self):
        menubar = self.menuBar()
        menubar.clear()

        if hasattr(menubar, "setNativeMenuBar"):
            menubar.setNativeMenuBar(sys.platform == "darwin")

        self._build_file_menu(menubar)
        self._build_edit_menu(menubar)
        self._build_view_menu(menubar)
        self._build_tools_menu(menubar)
        self._build_window_menu(menubar)
        self._build_help_menu(menubar)

    def _build_file_menu(self, menubar):
        file_menu = menubar.addMenu("&File")

        # Project workspace submenu
        project_menu = file_menu.addMenu("Project")

        self.action_new_project = QAction("New Project…", self)
        self.action_new_project.setShortcut("Ctrl+Shift+N")
        self.action_new_project.triggered.connect(self.new_project)
        project_menu.addAction(self.action_new_project)

        self.action_open_project = QAction("Open Project…", self)
        self.action_open_project.setShortcut("Ctrl+Shift+O")
        self.action_open_project.triggered.connect(self.open_project_file)
        project_menu.addAction(self.action_open_project)

        self.recent_projects_menu = project_menu.addMenu("Recent Projects")
        self.build_recent_projects_menu()

        project_menu.addSeparator()

        self.action_save_project = QAction("Save Project", self)
        self.action_save_project.setShortcut("Ctrl+Shift+S")
        self.action_save_project.triggered.connect(self.save_project_file)
        project_menu.addAction(self.action_save_project)

        self.action_save_project_as = QAction("Save Project As…", self)
        self.action_save_project_as.triggered.connect(self.save_project_file_as)
        project_menu.addAction(self.action_save_project_as)

        project_menu.addSeparator()

        self.action_add_experiment = QAction("Add Experiment", self)
        self.action_add_experiment.triggered.connect(self.add_experiment)
        project_menu.addAction(self.action_add_experiment)

        self.action_add_sample = QAction("Add Data", self)
        self.action_add_sample.triggered.connect(self.add_sample_to_current_experiment)
        project_menu.addAction(self.action_add_sample)

        file_menu.addSection("Session Data")

        self.action_new = QAction("Start New Analysis…", self)
        self.action_new.setShortcut(QKeySequence.New)
        self.action_new.triggered.connect(self.start_new_analysis)
        file_menu.addAction(self.action_new)

        self.action_open_trace = QAction("Open Trace & Events…", self)
        self.action_open_trace.setShortcut(QKeySequence.Open)
        self.action_open_trace.triggered.connect(self._handle_load_trace)
        file_menu.addAction(self.action_open_trace)

        self.action_open_tiff = QAction("Open Result TIFF…", self)
        self.action_open_tiff.setShortcut("Ctrl+Shift+T")
        self.action_open_tiff.triggered.connect(self.load_snapshot)
        file_menu.addAction(self.action_open_tiff)

        self.action_import_folder = QAction("Import Folder…", self)
        self.action_import_folder.setShortcut("Ctrl+Shift+I")
        self.action_import_folder.triggered.connect(self._handle_import_folder)
        file_menu.addAction(self.action_import_folder)

        self.recent_menu = file_menu.addMenu("Recent Files")
        self.update_recent_files_menu()

        file_menu.addSeparator()

        export_menu = file_menu.addMenu("Export")

        self.action_export_tiff = QAction("High-Res Plot…", self)
        self.action_export_tiff.triggered.connect(self.export_high_res_plot)
        export_menu.addAction(self.action_export_tiff)

        self.action_export_bundle = QAction("Project Bundle (.vasopack)…", self)
        self.action_export_bundle.triggered.connect(self.export_project_bundle_action)
        export_menu.addAction(self.action_export_bundle)

        self.action_export_shareable = QAction("Shareable Single File…", self)
        self.action_export_shareable.triggered.connect(self.export_shareable_project)
        export_menu.addAction(self.action_export_shareable)

        self.action_export_csv = QAction("Events as CSV…", self)
        self.action_export_csv.triggered.connect(self.auto_export_table)
        export_menu.addAction(self.action_export_csv)

        self.action_export_excel = QAction("To Excel Template…", self)
        self.action_export_excel.triggered.connect(self.open_excel_mapping_dialog)
        export_menu.addAction(self.action_export_excel)

        file_menu.addSeparator()

        self.action_preferences = QAction("Preferences…", self)
        self.action_preferences.setShortcut("Ctrl+,")
        self.action_preferences.triggered.connect(self.open_preferences_dialog)
        self._assign_menu_role(self.action_preferences, "PreferencesRole")
        file_menu.addAction(self.action_preferences)

        quit_text = "Quit VasoAnalyzer" if sys.platform == "darwin" else "Exit"
        self.action_exit = QAction(quit_text, self)
        self.action_exit.setShortcut(QKeySequence.Quit)
        self.action_exit.triggered.connect(self.close)
        self._assign_menu_role(self.action_exit, "QuitRole")
        file_menu.addAction(self.action_exit)

    def _build_edit_menu(self, menubar):
        edit_menu = menubar.addMenu("&Edit")

        undo = self.undo_stack.createUndoAction(self, "Undo")
        undo.setShortcut(QKeySequence.Undo)
        edit_menu.addAction(undo)

        redo = self.undo_stack.createRedoAction(self, "Redo")
        redo.setShortcut(QKeySequence.Redo)
        edit_menu.addAction(redo)

        edit_menu.addSeparator()

        # Event manipulation
        self.action_copy_events = QAction("Copy Event(s)", self)
        self.action_copy_events.setShortcut(QKeySequence.Copy)
        self.action_copy_events.triggered.connect(self.copy_selected_events)
        edit_menu.addAction(self.action_copy_events)

        self.action_paste_events = QAction("Paste Event(s)", self)
        self.action_paste_events.setShortcut(QKeySequence.Paste)
        self.action_paste_events.triggered.connect(self.paste_events)
        edit_menu.addAction(self.action_paste_events)

        self.action_duplicate_event = QAction("Duplicate Event", self)
        self.action_duplicate_event.setShortcut("Ctrl+D")
        self.action_duplicate_event.triggered.connect(self.duplicate_selected_event)
        edit_menu.addAction(self.action_duplicate_event)

        self.action_delete_event = QAction("Delete Event", self)
        self.action_delete_event.setShortcut(QKeySequence.Delete)
        self.action_delete_event.triggered.connect(self.delete_selected_events)
        edit_menu.addAction(self.action_delete_event)

        edit_menu.addSeparator()

        self.action_select_all_events = QAction("Select All Events", self)
        self.action_select_all_events.setShortcut(QKeySequence.SelectAll)
        self.action_select_all_events.triggered.connect(self.select_all_events)
        edit_menu.addAction(self.action_select_all_events)

        self.action_find_event = QAction("Find Event…", self)
        self.action_find_event.setShortcut(QKeySequence.Find)
        self.action_find_event.triggered.connect(self.find_event_dialog)
        edit_menu.addAction(self.action_find_event)

        edit_menu.addSeparator()

        clear_pins = QAction("Clear All Pins", self)
        clear_pins.triggered.connect(self.clear_all_pins)
        edit_menu.addAction(clear_pins)

        clear_events = QAction("Clear All Events", self)
        clear_events.triggered.connect(self.clear_current_session)
        edit_menu.addAction(clear_events)

    def _build_view_menu(self, menubar):
        view_menu = menubar.addMenu("&View")

        home_act = QAction("Show Home Screen", self)
        home_act.setShortcut("Ctrl+Shift+H")
        home_act.triggered.connect(self.show_home_screen)
        view_menu.addAction(home_act)

        view_menu.addSeparator()

        # Renderer selection
        renderer_menu = view_menu.addMenu("Renderer")
        self.action_use_matplotlib = QAction("Matplotlib", self, checkable=True)
        self.action_use_pyqtgraph = QAction("PyQtGraph", self, checkable=True)
        self.action_use_matplotlib.triggered.connect(lambda: self.set_renderer("matplotlib"))
        self.action_use_pyqtgraph.triggered.connect(lambda: self.set_renderer("pyqtgraph"))
        renderer_menu.addAction(self.action_use_matplotlib)
        renderer_menu.addAction(self.action_use_pyqtgraph)
        # Set default checked state
        self.action_use_matplotlib.setChecked(True)

        # Color scheme selection
        theme_menu = view_menu.addMenu("Color Scheme")
        self.action_theme_light = QAction("Light", self, checkable=True, checked=True)
        self.action_theme_dark = QAction("Dark", self, checkable=True)
        self.action_theme_auto = QAction("Auto (System)", self, checkable=True)
        self.action_theme_light.triggered.connect(lambda: self.set_color_scheme("light"))
        self.action_theme_dark.triggered.connect(lambda: self.set_color_scheme("dark"))
        self.action_theme_auto.triggered.connect(lambda: self.set_color_scheme("auto"))
        theme_menu.addAction(self.action_theme_light)
        theme_menu.addAction(self.action_theme_dark)
        theme_menu.addAction(self.action_theme_auto)

        view_menu.addSeparator()

        reset_act = QAction("Reset View", self)
        reset_act.setShortcut("Ctrl+R")
        reset_act.triggered.connect(self.reset_view)
        view_menu.addAction(reset_act)

        fit_act = QAction("Fit to Data", self)
        fit_act.setShortcut("Ctrl+F")
        fit_act.triggered.connect(self.fit_to_data)
        view_menu.addAction(fit_act)

        zoom_sel_act = QAction("Zoom to Selection", self)
        zoom_sel_act.setShortcut("Ctrl+E")
        zoom_sel_act.triggered.connect(self.zoom_to_selection)
        view_menu.addAction(zoom_sel_act)

        view_menu.addSeparator()

        anno_menu = view_menu.addMenu("Annotations")
        ev_lines = QAction("Event Lines", self, checkable=True, checked=True)
        ev_lbls = QAction("Event Labels", self)
        pin_lbls = QAction("Pinned Labels", self, checkable=True, checked=True)
        frame_mk = QAction("Frame Marker", self, checkable=True, checked=True)
        ev_lines.triggered.connect(lambda _: self.toggle_annotation("lines"))
        ev_lbls.triggered.connect(lambda _: self.toggle_annotation("evt_labels"))
        pin_lbls.triggered.connect(lambda _: self.toggle_annotation("pin_labels"))
        frame_mk.triggered.connect(lambda _: self.toggle_annotation("frame_marker"))
        for action in (ev_lines, ev_lbls, pin_lbls, frame_mk):
            anno_menu.addAction(action)
        self.menu_event_lines_action = ev_lines

        self._ensure_event_label_actions()
        label_modes_menu = anno_menu.addMenu("Label Mode")
        label_modes_menu.addAction(self.actEventLabelsVertical)
        label_modes_menu.addAction(self.actEventLabelsHorizontal)
        label_modes_menu.addAction(self.actEventLabelsOutside)

        view_menu.addSeparator()

        self.showhide_menu = view_menu.addMenu("Panels")
        evt_tbl = QAction("Event Table", self, checkable=True, checked=True)
        snap_vw = QAction("Snapshot Viewer", self, checkable=True, checked=False)
        evt_tbl.triggered.connect(self.toggle_event_table)
        snap_vw.triggered.connect(self.toggle_snapshot_viewer)
        self.showhide_menu.addAction(evt_tbl)
        self.showhide_menu.addAction(snap_vw)
        self.snapshot_viewer_action = snap_vw

        shortcut = "Meta+M" if sys.platform == "darwin" else "Ctrl+M"
        self.action_snapshot_metadata = QAction("Metadata…", self)
        self.action_snapshot_metadata.setShortcut(shortcut)
        self.action_snapshot_metadata.setCheckable(True)
        self.action_snapshot_metadata.setEnabled(False)
        self.action_snapshot_metadata.triggered.connect(
            lambda checked: self.set_snapshot_metadata_visible(bool(checked))
        )
        view_menu.addAction(self.action_snapshot_metadata)

        self.id_toggle_act = QAction("Inner", self, checkable=True, checked=True)
        self.id_toggle_act.setStatusTip("Show inner diameter trace")
        self.id_toggle_act.setToolTip("Toggle inner diameter trace")
        self.od_toggle_act = QAction("Outer", self, checkable=True, checked=True)
        self.od_toggle_act.setStatusTip("Show outer diameter trace")
        self.od_toggle_act.setToolTip("Toggle outer diameter trace")
        self.id_toggle_act.setShortcut("I")
        self.od_toggle_act.setShortcut("O")
        self.id_toggle_act.setIcon(QIcon(self.icon_path("ID.svg")))
        self.od_toggle_act.setIcon(QIcon(self.icon_path("OD.svg")))
        self.id_toggle_act.toggled.connect(self.toggle_inner_diameter)
        self.od_toggle_act.toggled.connect(self.toggle_outer_diameter)
        self.showhide_menu.addAction(self.id_toggle_act)
        self.showhide_menu.addAction(self.od_toggle_act)

        view_menu.addSeparator()

        fs_act = QAction("Full Screen", self)
        fs_act.setShortcut("F11")
        fs_act.triggered.connect(self.toggle_fullscreen)
        view_menu.addAction(fs_act)

    def _build_tools_menu(self, menubar):
        tools_menu = menubar.addMenu("&Tools")

        # Analysis tools
        analysis_menu = tools_menu.addMenu("Analysis")

        self.action_calculate_statistics = QAction("Calculate Statistics…", self)
        self.action_calculate_statistics.triggered.connect(self.show_statistics_dialog)
        analysis_menu.addAction(self.action_calculate_statistics)

        self.action_batch_analysis = QAction("Batch Analysis…", self)
        self.action_batch_analysis.triggered.connect(self.show_batch_analysis_dialog)
        analysis_menu.addAction(self.action_batch_analysis)

        self.action_validate_data = QAction("Data Validation…", self)
        self.action_validate_data.triggered.connect(self.show_data_validation_dialog)
        analysis_menu.addAction(self.action_validate_data)

        tools_menu.addSeparator()

        # Visualization tools
        self.action_plot_settings = QAction("Plot Settings…", self)
        self.action_plot_settings.triggered.connect(self.open_unified_plot_settings_dialog)
        tools_menu.addAction(self.action_plot_settings)

        layout_act = QAction("Subplot Layout…", self)
        layout_act.triggered.connect(self.open_subplot_layout_dialog)
        tools_menu.addAction(layout_act)

        tools_menu.addSeparator()

        # Data management tools
        self.action_map_excel = QAction("Map Events to Excel…", self)
        self.action_map_excel.triggered.connect(self.open_excel_mapping_dialog)
        tools_menu.addAction(self.action_map_excel)

        self.action_relink_assets = QAction("Relink Missing Files…", self)
        self.action_relink_assets.setEnabled(False)
        self.action_relink_assets.triggered.connect(self.show_relink_dialog)
        tools_menu.addAction(self.action_relink_assets)

    def _build_window_menu(self, menubar):
        window_menu = menubar.addMenu("&Window")

        minimize_act = QAction("Minimize", self)
        minimize_act.setShortcut("Ctrl+M" if sys.platform != "darwin" else "Meta+M")
        minimize_act.triggered.connect(self.showMinimized)
        window_menu.addAction(minimize_act)

        zoom_act = QAction("Zoom", self)
        zoom_act.triggered.connect(self.toggle_maximize)
        window_menu.addAction(zoom_act)

        window_menu.addSeparator()

        if sys.platform == "darwin":
            bring_all_act = QAction("Bring All to Front", self)
            bring_all_act.triggered.connect(self.raise_all_windows)
            window_menu.addAction(bring_all_act)

    def _build_help_menu(self, menubar):
        help_menu = menubar.addMenu("&Help")

        self.action_about = QAction("About VasoAnalyzer", self)
        self.action_about.triggered.connect(self.show_about)
        self._assign_menu_role(self.action_about, "AboutRole")
        help_menu.addAction(self.action_about)

        act_about_project = QAction("About Project File…", self)
        act_about_project.triggered.connect(self.show_project_file_info)
        help_menu.addAction(act_about_project)

        self.action_user_manual = QAction("User Manual…", self)
        self.action_user_manual.triggered.connect(self.open_user_manual)
        help_menu.addAction(self.action_user_manual)

        guide_act = QAction("Welcome Guide…", self)
        guide_act.setShortcut("Ctrl+/")
        guide_act.triggered.connect(lambda: self.show_welcome_guide(modal=False))
        help_menu.addAction(guide_act)

        tut_act = QAction("Quick Start Tutorial…", self)
        tut_act.triggered.connect(self.show_tutorial)
        help_menu.addAction(tut_act)

        help_menu.addSeparator()

        act_update = QAction("Check for Updates", self)
        act_update.triggered.connect(self.check_for_updates)
        help_menu.addAction(act_update)

        act_keys = QAction("Keyboard Shortcuts…", self)
        act_keys.triggered.connect(self.show_shortcuts)
        help_menu.addAction(act_keys)

        act_bug = QAction("Report a Bug…", self)
        act_bug.triggered.connect(
            lambda: webbrowser.open("https://github.com/vr-oj/VasoAnalyzer/issues/new")
        )
        help_menu.addAction(act_bug)

        act_rel = QAction("Release Notes…", self)
        act_rel.triggered.connect(self.show_release_notes)
        help_menu.addAction(act_rel)

    def show_project_file_info(self) -> None:
        message = (
            "<b>Single-File .vaso Projects</b><br><br>"
            "<ul>"
            "<li>SQLite v3 container that stores datasets, traces, UI state, and "
            "metadata together.</li>"
            "<li>All imported assets are embedded, deduplicated by SHA-256, and "
            "compressed for portability.</li>"
            "<li>Saves are atomic and crash-safe, with periodic autosave snapshots "
            "you can restore on reopen.</li>"
            "</ul>"
        )
        parent = self if isinstance(self, QWidget) else None
        QMessageBox.information(parent, "About Project File", message)

    def build_recent_files_menu(self):
        self.recent_menu.clear()

        if not self.recent_files:
            self.recent_menu.addAction("No recent files").setEnabled(False)
            return

        for path in self.recent_files:
            label = os.path.basename(path)
            action = QAction(label, self)
            action.setToolTip(path)
            action.triggered.connect(partial(self.load_trace_and_events, path))
            self.recent_menu.addAction(action)

        self.recent_menu.addSeparator()
        clear_action = QAction("Clear Recent Files", self)
        clear_action.triggered.connect(self.clear_recent_files)
        self.recent_menu.addAction(clear_action)

    def build_recent_projects_menu(self):
        if not hasattr(self, "recent_projects_menu") or self.recent_projects_menu is None:
            return
        self.recent_projects_menu.clear()

        if not self.recent_projects:
            self.recent_projects_menu.addAction("No recent projects").setEnabled(False)
            return

        for path in self.recent_projects:
            label = os.path.basename(path)
            action = QAction(label, self)
            action.setToolTip(path)
            action.triggered.connect(partial(self.open_recent_project, path))
            self.recent_projects_menu.addAction(action)

        self.recent_projects_menu.addSeparator()
        clear_action = QAction("Clear Recent Projects", self)
        clear_action.triggered.connect(self.clear_recent_projects)
        self.recent_projects_menu.addAction(clear_action)

    def open_preferences_dialog(self):
        from ..dialogs.preferences_dialog import PreferencesDialog

        dialog = PreferencesDialog(self)
        dialog.exec_()
