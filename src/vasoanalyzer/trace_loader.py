"""Helper routines for loading diameter trace CSV files."""


import csv
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

    # Auto-detect delimiter using the CSV sniffer
    with open(file_path, "r", encoding="utf-8-sig") as f:
        sample = f.read(1024)
        try:
            delimiter = csv.Sniffer().sniff(sample).delimiter
        except csv.Error:
            if "," in sample:
                delimiter = ","
            elif "\t" in sample:
                delimiter = "\t"
            else:
                delimiter = ";"

    df = pd.read_csv(file_path, delimiter=delimiter, encoding="utf-8-sig")

    # Drop any entirely empty columns that may appear due to malformed files
    df = df.dropna(axis=1, how="all")

    def _normalize(col):
        return re.sub(r"[^a-z0-9]", "", col.lower())

    # Locate time and diameter columns using flexible matching for legacy files
    time_col = None
    diam_col = None
    inner_candidates = []
    diam_candidates = []

    for c in df.columns:
        norm = _normalize(c)
        if time_col is None and (
            "time" in norm
            or "sec" in norm
            or norm in {"t", "ts"}
        ):
            time_col = c

        if "inner" in norm and "diam" in norm:
            inner_candidates.append(c)
        elif "diam" in norm or norm in {"id", "diameter"}:
            diam_candidates.append(c)

    if inner_candidates:
        diam_col = inner_candidates[0]
    elif diam_candidates:
        diam_col = diam_candidates[0]

    if time_col is None or diam_col is None or time_col == diam_col:
        raise ValueError("Trace file must contain Time and Inner Diameter columns")

    # Rename to standardized column names
    rename_map = {time_col: "Time (s)", diam_col: "Inner Diameter"}
    df = df.rename(columns=rename_map)
    df = df.loc[:, ~df.columns.duplicated()]

    # Ensure numeric types
    df["Time (s)"] = pd.to_numeric(df["Time (s)"], errors="coerce")
    df["Inner Diameter"] = pd.to_numeric(df["Inner Diameter"], errors="coerce")
    if "Outer Diameter" in df.columns:
        df = df.drop(columns=["Outer Diameter"])

    return df
