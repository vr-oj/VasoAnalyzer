from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Sequence

if TYPE_CHECKING:  # pragma: no cover
    from vasoanalyzer.ui.main_window import VasoAnalyzerApp


def open_project_file(window: "VasoAnalyzerApp", path: Optional[str] = None) -> None:
    """Delegate to the legacy project-open logic."""

    window._open_project_file_legacy(path)


def open_samples_in_dual_view(
    window: "VasoAnalyzerApp", samples: Optional[Sequence]
) -> None:
    """Delegate to the legacy dual-view opener."""

    window._open_samples_in_dual_view_legacy(samples)
