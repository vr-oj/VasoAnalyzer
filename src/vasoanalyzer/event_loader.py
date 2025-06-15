"""Utility to load event annotations from CSV or TXT files."""

import csv
import os
import re
import pandas as pd


def load_events(file_path):
    """Return event labels, times and optional frames from a table file.

    Args:
        file_path (str or Path): Path to the event table.

    Returns:
        tuple[list[str], list[float], list[int] | None]:
            A tuple of event labels, times in seconds and optional frame numbers
            (``None`` if the file lacks a frame column).

    Raises:
        pandas.errors.ParserError: If the file cannot be parsed.
        ValueError: If time values cannot be converted to seconds.
    """

    # Auto-detect delimiter using csv.Sniffer
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

    df = pd.read_csv(file_path, delimiter=delimiter)

    # Auto-detect columns with fallback for legacy headers
    def _normalize(col: str) -> str:
        """Return a simplified column name for matching."""
        return re.sub(r"[^a-z0-9]", "", col.lower())

    def _find_col(keywords, default=None):
        normed_cols = {col: _normalize(col) for col in df.columns}
        for col, norm in normed_cols.items():
            for kw in keywords:
                kw_norm = _normalize(kw)
                if norm == kw_norm or norm.startswith(kw_norm):
                    return col
        return default

    label_col = _find_col(["label", "event", "name"], df.columns[0])
    if len(df.columns) > 1:
        default_time = df.columns[1]
    else:
        default_time = df.columns[0]
    time_col = _find_col(["time"], default_time)
    frame_col = _find_col(["frame"])

    # Convert time to seconds
    time_series = df[time_col]
    if not pd.api.types.is_numeric_dtype(time_series):
        numeric = pd.to_numeric(time_series, errors="coerce")
        if numeric.notna().all():
            time_series = numeric
        else:
            time_series = pd.to_timedelta(time_series, errors="coerce").dt.total_seconds()
    time_sec = time_series

    labels = df[label_col].astype(str).tolist()
    times = time_sec.tolist()

    frames = None
    if frame_col:
        frames = df[frame_col].tolist()

    return labels, times, frames


def find_matching_event_file(trace_file: str) -> str | None:
    """Return the path to a matching event file if it exists."""
    base = os.path.splitext(os.path.basename(trace_file))[0]
    folder = os.path.dirname(trace_file)

    patterns = [
        f"{base}_table.csv",
        f"{base}_Table.csv",
        f"{base} table.csv",
        f"{base} Table.csv",
        f"{base} - table.csv",
        f"{base} - Table.csv",
        f"{base}_table.txt",
        f"{base}_Table.txt",
        f"{base} table.txt",
        f"{base} Table.txt",
        f"{base} - table.txt",
        f"{base} - Table.txt",
    ]

    for p in patterns:
        candidate = os.path.join(folder, p)
        if os.path.exists(candidate):
            return candidate
    return None


__all__ = ["load_events", "find_matching_event_file"]
