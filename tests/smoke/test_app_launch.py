"""Headless smoke test for the main VasoAnalyzer window."""

from __future__ import annotations

from pathlib import Path

from vasoanalyzer.core.project import Experiment, Project, SampleN
from vasoanalyzer.ui.main_window import VasoAnalyzerApp

from tests._sample_data import events_dataframe, trace_dataframe


def test_smoke_launch_and_export(qapp, tmp_path):
    window = VasoAnalyzerApp(check_updates=False)
    window._onboarding_checked = True
    window.autosave_timer.stop()
    window._event_highlight_timer.stop()

    trace_df = trace_dataframe()
    events_df = events_dataframe()
    sample = SampleN(name="Synthetic Sample", trace_data=trace_df, events_data=events_df)
    experiment = Experiment(name="Synthetic Experiment", samples=[sample])
    project = Project(
        name="Smoke Project",
        experiments=[experiment],
        path=str(tmp_path / "smoke.vaso"),
    )

    try:
        window._replace_current_project(project)
        window.refresh_project_tree()
        window.show_analysis_workspace()
        window.load_sample_into_view(sample)
        qapp.processEvents()

        window.toggle_annotation("lines")
        export_path = Path(tmp_path) / "smoke_trace.png"
        window.fig.savefig(export_path.as_posix(), dpi=160)
        qapp.processEvents()

        # Basic wiring sanity checks after refactors
        assert hasattr(window, "home_page") and window.home_page is not None
        assert hasattr(window, "toolbar") and window.toolbar is not None
        assert len(window.toolbar.actions()) > 0
        assert hasattr(window, "plot_host") and window.plot_host is not None

        assert export_path.exists()
        assert export_path.stat().st_size > 0
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()
