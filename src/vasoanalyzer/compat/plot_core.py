"""Temporary shim to keep legacy imports working.

Old code often does: `from vasoanalyzer.ui.plot_core import PlotHost`.
We forward that to the new location `vasoanalyzer.ui.plots.plot_host` and
emit a single DeprecationWarning.
"""

from __future__ import annotations

import warnings

warnings.warn(
    "Import path deprecated: use vasoanalyzer.ui.plots.plot_host",
    DeprecationWarning,
    stacklevel=2,
)

try:
    from vasoanalyzer.ui.plots.plot_host import *  # type: ignore # noqa: F401,F403
except Exception:  # pragma: no cover - during PR-002 the target may not exist
    pass

