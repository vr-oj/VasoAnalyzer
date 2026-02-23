"""Application bootstrap helpers."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vasoanalyzer.app.launcher import VasoAnalyzerLauncher

__all__ = ["VasoAnalyzerLauncher", "reload", "all_enabled", "is_enabled"]


def __getattr__(name: str):
    if name == "VasoAnalyzerLauncher":
        module = import_module("vasoanalyzer.app.launcher")
        value = module.VasoAnalyzerLauncher
    elif name in {"all_enabled", "is_enabled", "reload"}:
        module = import_module("vasoanalyzer.app.flags")
        value = getattr(module, name)
    else:
        raise AttributeError(f"module 'vasoanalyzer.app' has no attribute {name!r}")
    globals()[name] = value
    return value
