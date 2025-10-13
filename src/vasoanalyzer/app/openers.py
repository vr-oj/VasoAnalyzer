from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Sequence

from vasoanalyzer.core.project import close_project_ctx, open_project_ctx
from vasoanalyzer.core.project_context import ProjectContext

if TYPE_CHECKING:  # pragma: no cover
    from vasoanalyzer.ui.main_window import VasoAnalyzerApp


def open_project_file(window: "VasoAnalyzerApp", path: Optional[str] = None) -> None:
    """Open a project via the legacy flow while attaching a ProjectContext."""

    previous_project = getattr(window, "current_project", None)
    previous_ctx: Optional[ProjectContext] = getattr(window, "project_ctx", None)

    window._open_project_file_legacy(path)

    current_project = getattr(window, "current_project", None)
    if current_project is previous_project:
        return

    if previous_ctx is not None:
        try:
            close_project_ctx(previous_ctx)
        except Exception:
            pass

    project_path = getattr(current_project, "path", None)
    if project_path:
        ctx = open_project_ctx(project_path)
        window.project_ctx = ctx
        window.project_path = ctx.path
        window.project_meta = ctx.meta
    else:
        window.project_ctx = None
        window.project_path = None
        window.project_meta = {}


def open_samples_in_dual_view(
    window: "VasoAnalyzerApp", samples: Optional[Sequence]
) -> None:
    """Delegate to the legacy dual-view opener."""

    window._open_samples_in_dual_view_legacy(samples)
