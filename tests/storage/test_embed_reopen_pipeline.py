import pandas as pd

from vasoanalyzer.storage import sqlite_store


def _trace_df(seed: float) -> pd.DataFrame:
    base = seed * 10.0
    return pd.DataFrame(
        {
            "Time (s)": [0.0, 1.0, 2.0],
            "Inner Diameter": [base + 1, base + 2, base + 3],
            "Outer Diameter": [base + 11, base + 12, base + 13],
            "Avg Pressure (mmHg)": [base + 21, base + 22, base + 23],
            "Set Pressure (mmHg)": [base + 31, base + 32, base + 33],
        }
    )


def _events_df(seed: float) -> pd.DataFrame:
    base = seed * 5.0
    return pd.DataFrame(
        {
            "Time (s)": [0.25, 1.25],
            "Event": [f"Stim_{seed}_A", f"Stim_{seed}_B"],
            "Frame": [0, 1],
            "DiamBefore": [base + 100, base + 110],
            "OuterDiamBefore": [base + 200, base + 210],
            "p_avg": [base + 50, base + 55],
            "p2": [base + 60, base + 65],
        }
    )


def test_embed_and_reopen_preserves_trace_and_events(tmp_path):
    project_path = tmp_path / "embed_roundtrip.vaso"
    store = sqlite_store.create_project(project_path, app_version="test", timezone="UTC")
    datasets: list[tuple[int, pd.DataFrame, pd.DataFrame]] = []
    try:
        for idx in range(1, 4):
            trace_df = _trace_df(idx)
            events_df = _events_df(idx)
            dataset_id = sqlite_store.add_dataset(
                store,
                f"sample_{idx}",
                trace_df,
                events_df,
                metadata={"notes": f"sample {idx}"},
            )
            datasets.append((dataset_id, trace_df, events_df))
        sqlite_store.save_project(store)
    finally:
        sqlite_store.close_project(store)

    reopened = sqlite_store.open_project(project_path)
    try:
        for dataset_id, original_trace, original_events in datasets:
            trace_roundtrip = sqlite_store.get_trace(reopened, dataset_id)
            assert len(trace_roundtrip.index) == len(original_trace.index)
            assert trace_roundtrip["inner_diam"].tolist() == original_trace[
                "Inner Diameter"
            ].tolist()
            assert trace_roundtrip["outer_diam"].tolist() == original_trace[
                "Outer Diameter"
            ].tolist()
            assert trace_roundtrip["p_avg"].tolist() == original_trace[
                "Avg Pressure (mmHg)"
            ].tolist()
            assert trace_roundtrip["p2"].tolist() == original_trace["Set Pressure (mmHg)"].tolist()

            events_roundtrip = sqlite_store.get_events(reopened, dataset_id)
            assert len(events_roundtrip.index) == len(original_events.index)
            # Extra payload stores DiamBefore / OuterDiamBefore
            assert "extra" in events_roundtrip.columns
            for idx, payload in enumerate(events_roundtrip["extra"]):
                assert payload["DiamBefore"] == original_events.iloc[idx]["DiamBefore"]
                assert payload["OuterDiamBefore"] == original_events.iloc[idx]["OuterDiamBefore"]
    finally:
        sqlite_store.close_project(reopened)
