import os
import numpy as np
import logging
from .trace_loader import load_trace
from .event_loader import load_events, find_matching_event_file

log = logging.getLogger(__name__)


def load_trace_and_events(trace_path: str, events_path: str | None = None):
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
    tuple[pandas.DataFrame, list[str], list[float], list[int] | None, list[float]]
        The trace DataFrame followed by event labels, times, frame indices (or
        ``None`` if unavailable) and the diameter at each event time.
    """
    log.info("Loading trace and events for %s", trace_path)
    df = load_trace(trace_path)

    if events_path is None:
        events_path = find_matching_event_file(trace_path)

    if events_path and os.path.exists(events_path):
        log.info("Found event file: %s", events_path)
    else:
        log.info("No event file found for %s", trace_path)

    labels, times, frames, diam = [], [], None, []
    if events_path and os.path.exists(events_path):
        labels, times, frames = load_events(events_path)
        log.info("Loaded %d events", len(labels))
        if frames is None:
            arr_t = df["Time (s)"].values
            frames = [int(np.argmin(np.abs(arr_t - t))) for t in times]
        arr_t = df["Time (s)"].values
        arr_d = df["Inner Diameter"].values
        diam = [float(arr_d[int(np.argmin(np.abs(arr_t - t)))]) for t in times]

    log.info("Trace and events loaded: %d events", len(labels))
    return df, labels, times, frames, diam

__all__ = ["load_trace_and_events"]
