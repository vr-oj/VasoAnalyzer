import pandas as pd


def load_trace(file_path):
    """Load a trace CSV and return a DataFrame with standardized columns.

    The loader searches for columns representing time and inner diameter,
    renaming them to ``"Time (s)"`` and ``"Inner Diameter"`` respectively.
    If either column is missing an exception is raised.
    """

    # Try to auto-detect delimiter from the first line
    with open(file_path, "r", encoding="utf-8-sig") as f:
        first_line = f.readline()
        delimiter = "," if "," in first_line else "\t"

    df = pd.read_csv(file_path, delimiter=delimiter, encoding="utf-8-sig")

    # Locate time and diameter columns
    time_col = next((c for c in df.columns if "time" in c.lower()), None)
    diam_col = next((c for c in df.columns if "inner" in c.lower() and "diam" in c.lower()), None)

    if time_col is None or diam_col is None:
        raise ValueError("Trace file must contain Time and Inner Diameter columns")

    # Rename to standardized column names
    df = df.rename(columns={time_col: "Time (s)", diam_col: "Inner Diameter"})

    # Ensure numeric types
    df["Time (s)"] = pd.to_numeric(df["Time (s)"], errors="coerce")
    df["Inner Diameter"] = pd.to_numeric(df["Inner Diameter"], errors="coerce")

    return df
