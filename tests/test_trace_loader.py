import pandas as pd
from vasoanalyzer.trace_loader import load_trace


def test_load_trace_column_detection(tmp_path):
    csv_path = tmp_path / "trace.csv"
    df = pd.DataFrame({"Time": [0, 1, 2], "Inner Diameter ": [10, 11, 12]})
    df.to_csv(csv_path, index=False)

    loaded = load_trace(str(csv_path))
    assert "Time (s)" in loaded.columns
    assert "Inner Diameter" in loaded.columns
    assert loaded["Time (s)"].tolist() == [0, 1, 2]
    assert loaded["Inner Diameter"].tolist() == [10, 11, 12]


def test_load_trace_duplicate_columns(tmp_path):
    csv_path = tmp_path / "dup.csv"
    df = pd.DataFrame({
        "Time": [0, 1],
        "Inner Diameter": [5, 6],
        "Time (s)": [0, 1],
    })
    df.to_csv(csv_path, index=False)

    loaded = load_trace(str(csv_path))
    assert loaded.shape[1] == 2
    assert loaded["Time (s)"].tolist() == [0, 1]
    assert loaded["Inner Diameter"].tolist() == [5, 6]


def test_load_trace_outer_diameter(tmp_path):
    csv_path = tmp_path / "outer.csv"
    df = pd.DataFrame(
        {
            "Time": [0, 1, 2],
            "Inner Diameter": [10, 11, 12],
            "OD": [15, 16, 17],
        }
    )
    df.to_csv(csv_path, index=False)

    loaded = load_trace(str(csv_path))
    assert "Outer Diameter" in loaded.columns
    assert loaded["Outer Diameter"].tolist() == [15, 16, 17]

