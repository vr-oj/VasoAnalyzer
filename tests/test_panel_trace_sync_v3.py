import pandas as pd
import pytest
from PyQt6.QtCore import QItemSelectionModel

from vasoanalyzer.core.project import SampleN
from vasoanalyzer.ui.main_window import VasoAnalyzerApp


def _make_trace_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Time (s)": [0.0, 1.0, 2.0, 3.0],
            "Inner Diameter": [10.0, 11.0, 12.0, 13.0],
        }
    )


def _make_events_df(labels: list[str], times: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"Event": labels, "Time (s)": times})


def test_dataset_switch_updates_event_table(qt_app) -> None:
    window = VasoAnalyzerApp(check_updates=False)
    try:
        sample_a = SampleN(
            name="A",
            trace_data=_make_trace_df(),
            events_data=_make_events_df(["A1", "A2"], [0.5, 1.0]),
        )
        sample_b = SampleN(
            name="B",
            trace_data=_make_trace_df(),
            events_data=_make_events_df(["B1"], [2.0]),
        )

        window.load_sample_into_view(sample_a)
        assert [row[0] for row in window.event_table_data] == ["A1", "A2"]

        window.load_sample_into_view(sample_b)
        assert [row[0] for row in window.event_table_data] == ["B1"]
    finally:
        window.close()
        qt_app.processEvents()


def test_event_selection_moves_cursor(qt_app) -> None:
    window = VasoAnalyzerApp(check_updates=False)
    try:
        sample = SampleN(
            name="Focus",
            trace_data=_make_trace_df(),
            events_data=_make_events_df(["E1"], [1.0]),
        )
        window.load_sample_into_view(sample)

        plot_host = window.plot_host
        window_range = plot_host.current_window()
        if window_range is None:
            plot_host.set_time_window(0.0, 3.0)
            window_range = plot_host.current_window()

        assert window_range is not None
        before_width = window_range[1] - window_range[0]

        window.table_row_clicked(0, 1)

        assert window._time_cursor_time == pytest.approx(1.0, abs=1e-6)
        after_range = plot_host.current_window()
        assert after_range is not None
        assert (after_range[1] - after_range[0]) == pytest.approx(before_width, abs=1e-6)
    finally:
        window.close()
        qt_app.processEvents()


def test_multi_select_event_focus_is_deterministic(qt_app) -> None:
    window = VasoAnalyzerApp(check_updates=False)
    try:
        sample = SampleN(
            name="Multi",
            trace_data=_make_trace_df(),
            events_data=_make_events_df(["Late", "Early"], [2.0, 1.0]),
        )
        window.load_sample_into_view(sample)

        model = window.event_table.model()
        selection = window.event_table.selectionModel()
        assert model is not None
        assert selection is not None

        selection.clearSelection()
        first = model.index(0, 1)
        second = model.index(1, 1)
        selection.select(first, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
        selection.select(second, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
        qt_app.processEvents()

        assert window._time_cursor_time == pytest.approx(1.0, abs=1e-6)
    finally:
        window.close()
        qt_app.processEvents()
