"""Runtime hook: ensure pytz.__version__ is set before pandas loads.

pandas._libs.tslibs.timezones calls import_optional_dependency('pytz') during
C-extension init, which requires pytz.__version__ to be a non-None string.
In some PyInstaller builds pytz is collected but its __version__ is None or
missing because pytz sets it dynamically via importlib.metadata, and the
.dist-info directory isn't found early enough. This hook imports pytz first
and patches the attribute so pandas never sees a None version.
"""
try:
    import pytz as _pytz  # noqa: F401

    if not getattr(_pytz, "__version__", None):
        try:
            import importlib.metadata as _meta

            _pytz.__version__ = _meta.version("pytz")
        except Exception:
            _pytz.__version__ = "2024.1"  # safe fallback; pandas only needs a non-None string
except ImportError:
    pass
