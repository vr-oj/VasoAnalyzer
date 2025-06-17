import os
import csv
import logging
import numpy as np
import pandas as pd

from .trace_loader import load_trace
from .event_loader import (
    load_events,
    find_matching_event_file,
    _standardize_headers,
)


def _read_event_dataframe(path: str) -> pd.DataFrame:
    """Return ``path`` loaded into a DataFrame with normalized headers."""
    with open(path, "r", encoding="utf-8-sig") as f:
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
    df = pd.read_csv(path, delimiter=delimiter)
    return _standardize_headers(df)

log = logging.getLogger(__name__)


def load_trace_and_events(trace_path: str, events_path: str | pd.DataFrame | None = None):
    """Load a trace CSV and its matching event table.

    Parameters
    ----------
    trace_path:
        Path to the trace CSV file.
    events_path:
        Optional explicit path to the event file. If ``None``, a matching
        file is searched next to ``trace_path`` using
        :func:`find_matching_event_file`.

    Returns
    -------
    tuple[pandas.DataFrame, list[str], list[float], list[int] | None, list[float], list[float]]
        The trace DataFrame followed by event labels, times, frame indices (or
        ``None`` if unavailable) and the inner and outer diameter at each event time.
    """
    log.info("Loading trace and events for %s", trace_path)
    df = load_trace(trace_path)

    events_df = None
    ev_path = None

    if isinstance(events_path, pd.DataFrame):
        events_df = _standardize_headers(events_path.copy())
    else:
        ev_path = events_path

    if ev_path is None and events_df is None:
        ev_path = find_matching_event_file(trace_path)

    if ev_path and os.path.exists(ev_path):
        log.info("Found event file: %s", ev_path)
    elif events_df is None:
        log.info("No event file found for %s", trace_path)

    labels: list[str] = []
    times: list[float] = []
    frames: list[int] | None = None
    diam: list[float] = []
    od_diam: list[float] = []

    if events_df is not None or (ev_path and os.path.exists(ev_path)):
        if events_df is None:
            events_df = _read_event_dataframe(ev_path)
            labels, times, frames = load_events(ev_path)
        else:
            labels = events_df[events_df.columns[0]].astype(str).tolist()
            if "Time" in events_df.columns:
                times = pd.to_numeric(events_df["Time"], errors="coerce").tolist()
            elif "Time (s)" in events_df.columns:
                times = pd.to_numeric(events_df["Time (s)"], errors="coerce").tolist()
            else:
                times = pd.to_numeric(events_df[events_df.columns[1]], errors="coerce").tolist()
            frames = (
                events_df["Frame"].astype(int).tolist() if "Frame" in events_df.columns else None
            )

        log.info("Loaded %d events", len(labels))

        arr_t = df["Time (s)"].values
        if not diam:
            if "DiamBefore" in events_df.columns:
                diam = pd.to_numeric(events_df["DiamBefore"], errors="coerce").astype(float).tolist()
            else:
                arr_d = df["Inner Diameter"].values
                diam = [float(arr_d[int(np.argmin(np.abs(arr_t - t)))]) for t in times]
        if "Outer Diameter" in df.columns:
            arr_od = df["Outer Diameter"].values
            od_diam = [float(arr_od[int(np.argmin(np.abs(arr_t - t)))]) for t in times]

        if frames is None:
            frames = [int(np.argmin(np.abs(arr_t - t))) for t in times]

    log.info("Trace and events loaded: %d events", len(labels))
    return df, labels, times, frames, diam, od_diam

__all__ = ["load_trace_and_events"]
