import pandas as pd

from vasoanalyzer.core import project as project_module
from vasoanalyzer.storage import sqlite_store


def _sample_trace_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Time (s)": [0.0, 1.0],
            "Inner Diameter": [10.0, 11.0],
            "Outer Diameter": [20.0, 21.0],
            "Avg Pressure (mmHg)": [50.0, 51.0],
            "Set Pressure (mmHg)": [60.0, 61.0],
        }
    )


def test_set_pressure_round_trip_default_label(tmp_path):
    store = sqlite_store.create_project(
        tmp_path / "proj.sqlite",
        app_version="test",
        timezone="UTC",
    )
    try:
        dataset_id = sqlite_store.add_dataset(
            store,
            "sample",
            _sample_trace_df(),
            None,
            metadata={},
        )
        trace_raw = sqlite_store.get_trace(store, dataset_id)
        formatted = project_module._format_trace_df(
            trace_raw, {"p2": "Set Pressure (mmHg)"}, "sample"
        )
        assert formatted is not None
        assert "Set Pressure (mmHg)" in formatted.columns
        assert list(formatted["Set Pressure (mmHg)"]) == [60.0, 61.0]
    finally:
        store.close()


def test_set_pressure_round_trip_custom_label(tmp_path):
    store = sqlite_store.create_project(
        tmp_path / "proj_custom.sqlite",
        app_version="test",
        timezone="UTC",
    )
    try:
        dataset_id = sqlite_store.add_dataset(
            store,
            "sample",
            _sample_trace_df(),
            None,
            metadata={},
        )
        trace_raw = sqlite_store.get_trace(store, dataset_id)
        custom_label = "Custom Set Pressure"
        formatted = project_module._format_trace_df(trace_raw, {"p2": custom_label}, "sample")
        assert formatted is not None
        assert custom_label in formatted.columns
        assert list(formatted[custom_label]) == [60.0, 61.0]
    finally:
        store.close()


def test_format_trace_df_normalizes_p2_alias():
    df = pd.DataFrame(
        {
            "t_seconds": [0.0, 1.0],
            "inner_diam": [10.0, 11.0],
            "outer_diam": [20.0, 21.0],
            "p_avg": [30.0, 31.0],
            "p1": [40.0, 41.0],
            "p2": [50.0, 51.0],
        }
    )
    formatted = project_module._format_trace_df(
        df,
        {"p2": "Pressure 2 (mmHg)"},
        "sample",
    )
    assert "Set Pressure (mmHg)" in formatted.columns
    assert formatted["Set Pressure (mmHg)"].tolist() == [50.0, 51.0]


def test_normalize_p2_label_aliases():
    assert (
        project_module.normalize_p2_label("Pressure 2 (mmHg)")
        == project_module.P2_CANONICAL_LABEL
    )
    assert (
        project_module.normalize_p2_label("Set P (mmHg)")
        == project_module.P2_CANONICAL_LABEL
    )
    assert project_module.normalize_p2_label("Custom Label") == "Custom Label"


def test_set_pressure_values_round_trip(tmp_path):
    store = sqlite_store.create_project(
        tmp_path / "proj_values.sqlite",
        app_version="test",
        timezone="UTC",
    )
    try:
        trace_df = pd.DataFrame(
            {
                "Time (s)": [0.0, 1.0, 2.0, 3.0, 4.0],
                "Inner Diameter": [10, 11, 12, 13, 14],
                "Outer Diameter": [20, 21, 22, 23, 24],
                "Avg Pressure (mmHg)": [5, 10, 15, 20, 25],
                "Set Pressure (mmHg)": [0, 10, 20, 30, 40],
                "Pressure 1 (mmHg)": [1, 2, 3, 4, 5],
                "Pressure 2 (mmHg)": [99, 98, 97, 96, 95],
            }
        )
        dataset_id = sqlite_store.add_dataset(
            store,
            "sample",
            trace_df,
            None,
            metadata={},
        )
        reopened = sqlite_store.get_trace(store, dataset_id)
        formatted = project_module._format_trace_df(
            reopened,
            {"p2": "Set Pressure (mmHg)"},
            "sample",
        )
        assert formatted is not None
        assert "Set Pressure (mmHg)" in formatted.columns
        assert formatted["Set Pressure (mmHg)"].tolist() == trace_df["Set Pressure (mmHg)"].tolist()
    finally:
        store.close()
