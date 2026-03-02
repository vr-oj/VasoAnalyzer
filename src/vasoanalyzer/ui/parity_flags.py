"""Feature flags for chart-view parity behavior."""

from __future__ import annotations

from vasoanalyzer.app.flags import is_enabled


def chart_view_parity_v1_enabled() -> bool:
    """Return whether chart-view parity behavior v1 is enabled."""
    return bool(is_enabled("ui.parity_chart_view_v1", default=True))

