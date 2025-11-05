"""Application services for higher-level orchestration."""

from importlib import import_module
from typing import Any

__all__ = [
    "manifest_to_project",
    "open_project_file",
    "save_project_file",
    "autosave_project",
    "pending_autosave_path",
    "restore_autosave",
    "export_project_bundle",
    "import_project_bundle",
    "check_for_new_version",
    "service_types",
    "open_project_repository",
    "create_project_repository",
    "convert_project_repository",
    "SQLiteProjectRepository",
]

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "manifest_to_project": ("vasoanalyzer.services.project_service", "manifest_to_project"),
    "open_project_file": ("vasoanalyzer.services.project_service", "open_project_file"),
    "save_project_file": ("vasoanalyzer.services.project_service", "save_project_file"),
    "autosave_project": ("vasoanalyzer.services.project_service", "autosave_project"),
    "pending_autosave_path": ("vasoanalyzer.services.project_service", "pending_autosave_path"),
    "restore_autosave": ("vasoanalyzer.services.project_service", "restore_autosave"),
    "export_project_bundle": ("vasoanalyzer.services.project_service", "export_project_bundle"),
    "import_project_bundle": ("vasoanalyzer.services.project_service", "import_project_bundle"),
    "open_project_repository": ("vasoanalyzer.services.project_service", "open_project_repository"),
    "create_project_repository": (
        "vasoanalyzer.services.project_service",
        "create_project_repository",
    ),
    "convert_project_repository": (
        "vasoanalyzer.services.project_service",
        "convert_project_repository",
    ),
    "SQLiteProjectRepository": ("vasoanalyzer.services.project_service", "SQLiteProjectRepository"),
    "check_for_new_version": ("vasoanalyzer.services.version", "check_for_new_version"),
}


def __getattr__(name: str) -> Any:
    if name == "service_types":
        module = import_module("vasoanalyzer.services.types")
        globals()[name] = module
        return module

    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module 'vasoanalyzer.services' has no attribute {name!r}")

    module_name, attr_name = target
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
