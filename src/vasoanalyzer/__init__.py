# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Public package interface for the VasoAnalyzer application."""

from importlib import import_module

from vasoanalyzer.core.project import (
    Experiment,
    Project,
    SampleN,
    autosave_path_for,
    export_sample,
    load_project,
    pack_project_bundle,
    restore_project_from_autosave,
    save_project,
    unpack_project_bundle,
    write_project_autosave,
)
from vasoanalyzer.core.project import (
    _save_project_legacy_zip as save_project_legacy,
)
from vasoanalyzer.services.project_service import (
    autosave_project,
    export_project_bundle,
    import_project_bundle,
    open_project_file,
    pending_autosave_path,
    restore_autosave,
    save_project_file,
)

_UI_EXPORTS = {
    "ReplaceEventCommand": ("vasoanalyzer.ui.commands", "ReplaceEventCommand"),
    "AxisSettingsDialog": ("vasoanalyzer.ui.dialogs.axis_settings_dialog", "AxisSettingsDialog"),
    "SubplotLayoutDialog": ("vasoanalyzer.ui.dialogs.subplot_layout_dialog", "SubplotLayoutDialog"),
    "ExcelMapWizard": ("vasoanalyzer.ui.dialogs.excel_map_wizard", "ExcelMapWizard"),
    "VasoAnalyzerApp": ("vasoanalyzer.ui.main_window", "VasoAnalyzerApp"),
    "ProjectExplorerWidget": ("vasoanalyzer.ui.project_explorer", "ProjectExplorerWidget"),
}


def __getattr__(name: str):
    if name in _UI_EXPORTS:
        module_name, attr = _UI_EXPORTS[name]
        module = import_module(module_name)
        value = getattr(module, attr)
        globals()[name] = value
        return value
    raise AttributeError(f"module 'vasoanalyzer' has no attribute {name!r}")


open_project = load_project

__all__ = [
    "VasoAnalyzerApp",
    "AxisSettingsDialog",
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
