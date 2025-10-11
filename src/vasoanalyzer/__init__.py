# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Public package interface for the VasoAnalyzer application."""

from vasoanalyzer.core.project import (
    Project,
    Experiment,
    SampleN,
    export_sample,
    load_project,
    save_project,
    _save_project_legacy_zip as save_project_legacy,
    pack_project_bundle,
    unpack_project_bundle,
    write_project_autosave,
    restore_project_from_autosave,
    autosave_path_for,
)
from vasoanalyzer.services.project_service import (
    open_project_file,
    save_project_file,
    autosave_project,
    pending_autosave_path,
    restore_autosave,
    export_project_bundle,
    import_project_bundle,
)
from vasoanalyzer.ui.commands import ReplaceEventCommand
from vasoanalyzer.ui.dialogs.axis_settings_dialog import AxisSettingsDialog
from vasoanalyzer.ui.dialogs.plot_style_editor import PlotStyleEditor
from vasoanalyzer.ui.dialogs.subplot_layout_dialog import SubplotLayoutDialog
from vasoanalyzer.ui.dialogs.excel_map_wizard import ExcelMapWizard
from vasoanalyzer.ui.main_window import VasoAnalyzerApp
from vasoanalyzer.ui.project_explorer import ProjectExplorerWidget

open_project = load_project

__all__ = [
    "VasoAnalyzerApp",
    "AxisSettingsDialog",
    "PlotStyleEditor",
    "SubplotLayoutDialog",
    "ReplaceEventCommand",
    "Project",
    "Experiment",
    "SampleN",
    "export_sample",
    "load_project",
    "save_project",
    "save_project_legacy",
    "pack_project_bundle",
    "unpack_project_bundle",
    "write_project_autosave",
    "restore_project_from_autosave",
    "autosave_path_for",
    "autosave_project",
    "pending_autosave_path",
    "restore_autosave",
    "export_project_bundle",
    "import_project_bundle",
    "open_project",
    "open_project_file",
    "save_project_file",
    "ProjectExplorerWidget",
    "ExcelMapWizard",
]
