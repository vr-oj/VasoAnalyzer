"""Helper routines for loading diameter trace CSV files."""

import re

import pandas as pd


def load_trace(file_path):
    """Load a trace CSV and return a standardized DataFrame.

    Args:
        file_path (str or Path): Path to the CSV file.

    Returns:
        pandas.DataFrame: Data with ``"Time (s)"`` and ``"Inner Diameter"``
        columns converted to numeric types.

    Raises:
        ValueError: If no time or inner diameter column can be found.
        pandas.errors.ParserError: If the CSV cannot be parsed.
    """

    # Try to auto-detect delimiter from the first line
    with open(file_path, "r", encoding="utf-8-sig") as f:
        first_line = f.readline()
        delimiter = "," if "," in first_line else "\t"

    df = pd.read_csv(file_path, delimiter=delimiter, encoding="utf-8-sig")

    def _normalize(col):
        return re.sub(r"[^a-z0-9]", "", col.lower())

    # Locate time and diameter columns using flexible matching for legacy files
    time_col = None
    diam_col = None
    for c in df.columns:
        norm = _normalize(c)
        if time_col is None and ("time" in norm or "sec" in norm or norm == "t"):
            time_col = c
        if diam_col is None and (
            ("inner" in norm and "diam" in norm)
            or "diam" in norm
            or norm in {"id", "diameter"}
        ):
            diam_col = c
        if time_col and diam_col:
            break

    if time_col is None or diam_col is None:
        raise ValueError("Trace file must contain Time and Inner Diameter columns")

    # Rename to standardized column names
    df = df.rename(columns={time_col: "Time (s)", diam_col: "Inner Diameter"})

    # Ensure numeric types
    df["Time (s)"] = pd.to_numeric(df["Time (s)"], errors="coerce")
    df["Inner Diameter"] = pd.to_numeric(df["Inner Diameter"], errors="coerce")

    return df
