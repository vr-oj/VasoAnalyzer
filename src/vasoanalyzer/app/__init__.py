"""Application bootstrap helpers."""

from importlib import import_module

__all__ = ["VasoAnalyzerLauncher", "all_enabled", "is_enabled", "reload"]


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
