import os
import csv
import logging
import re
import numpy as np
import pandas as pd

from .event_loader import _standardize_headers

log = logging.getLogger(__name__)


def is_legacy_event(path: str) -> bool:
    """Return True if ``path`` appears to be a legacy event table."""
    name = os.path.basename(path).lower()
    if "table" in name and "_table" not in name:
        return True
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            header = f.readline().lower()
    except Exception:
        header = ""
    if "diameterbefore" in header or "diam before" in header:
        return False
    if "event" in header and "label" not in header:
        return True
    return False


def load_events(file_path: str, trace_df: pd.DataFrame | None = None):
    """Load legacy events.``
    Returns labels, times, frames, and diameters (if available)."""
    log.info("Loading legacy events from %s", file_path)
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

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [" ".join(str(part) for part in col if pd.notna(part)) for col in df.columns]

    df = _standardize_headers(df)

    def _norm(c: str) -> str:
        return re.sub(r"[^a-z0-9]", "", c.lower())

    label_col = "EventLabel" if "EventLabel" in df.columns else df.columns[0]
    time_col = "Time" if "Time" in df.columns else [c for c in df.columns if c != label_col][0]

    labels = df[label_col].astype(str).tolist()
    time_series = df[time_col]
    if not pd.api.types.is_numeric_dtype(time_series):
        numeric = pd.to_numeric(time_series, errors="coerce")
        if numeric.notna().all():
            time_series = numeric
        else:
            time_series = pd.to_timedelta(time_series, errors="coerce").dt.total_seconds()
    times = time_series.tolist()

    frame_col = None
    for c in df.columns:
        if _norm(c).startswith("frame"):
            frame_col = c
            break
    frames = df[frame_col].astype(int).tolist() if frame_col else None

    diam = None
    if "DiamBefore" in df.columns:
        diam = pd.to_numeric(df["DiamBefore"], errors="coerce").astype(float).tolist()
    elif trace_df is not None:
        arr_t = trace_df["Time (s)"].values
        arr_d = trace_df["Inner Diameter"].values
        diam = [float(arr_d[int(np.argmin(np.abs(arr_t - t)))]) for t in times]

    return labels, times, frames, diam


__all__ = ["load_events", "is_legacy_event"]
