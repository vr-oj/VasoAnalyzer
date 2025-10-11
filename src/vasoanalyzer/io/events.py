# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Utility helpers to load event annotations from CSV or TXT files."""

from __future__ import annotations

import csv
import logging
import os
import re
from pathlib import Path
from typing import Iterable

import pandas as pd

try:
    from vasoanalyzer.services.cache_service import DataCache
except Exception:  # pragma: no cover - optional during bootstrap
    DataCache = None  # type: ignore

log = logging.getLogger(__name__)

HEADER_ALIASES: dict[str, str] = {
    # Time
    "time": "Time",
    "timestamp": "Time",
    "eventtime": "Time",
    "eventtimestamp": "Time",
    "times": "Time",
    "timesec": "Time",
    "timeseconds": "Time",
    "time_seconds": "Time",
    "timehhmmss": "Time",
    # Frame
    "frame": "Frame",
    "frame#": "Frame",
    "frameindex": "Frame",
    "frameid": "Frame",
    "#frame": "Frame",
    # Labels
    "event": "EventLabel",
    "events": "EventLabel",
    "label": "EventLabel",
    "eventlabel": "EventLabel",
    "eventname": "EventLabel",
    "name": "EventLabel",
    # Inner diameter / ID
    "id": "DiamBefore",
    "innerdiameter": "DiamBefore",
    "innerdiam": "DiamBefore",
    "innertube": "DiamBefore",
    "diameter": "DiamBefore",
    "inner": "DiamBefore",
    "diambefore": "DiamBefore",
    "diameterbefore": "DiamBefore",
    # Outer diameter / OD
    "od": "OuterDiamBefore",
    "outerdiameter": "OuterDiamBefore",
    "outerdiam": "OuterDiamBefore",
    "diameterafter": "OuterDiamBefore",
    # Pressure / misc
    "pavg": "Pavg",
    "avgpressure": "Pavg",
    "pressureavg": "Pavg",
    "p1": "P1",
    "p2": "P2",
    "temp": "Temp",
    "temperature": "Temp",
    "caliper": "Caliper",
}


def _standardize_headers(df: pd.DataFrame) -> pd.DataFrame:
    """Return ``df`` with legacy headers renamed to current names."""

    rename_map = {}
    for col in df.columns:
        norm = _normalize_column_name(col)
        if norm in HEADER_ALIASES:
            rename_map[col] = HEADER_ALIASES[norm]
        elif norm in {"t", "ts"}:
            rename_map[col] = "Time"
        elif norm.startswith("diameterbefore"):
            rename_map[col] = "DiamBefore"
    if rename_map:
        df = df.rename(columns=rename_map)
    return df


def _normalize_column_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _is_numeric_or_time_series(series: pd.Series) -> bool:
    if series.empty:
        return False

    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().mean() >= 0.8:
        return True

    td = pd.to_timedelta(series, errors="coerce")
    return td.notna().mean() >= 0.8


def _find_column(
    df: pd.DataFrame,
    keywords: Iterable[str],
    default=None,
    *,
    exclude: Iterable[str] | None = None,
):
    normed_cols = {col: _normalize_column_name(col) for col in df.columns}
    exclude_norm = [_normalize_column_name(e) for e in exclude] if exclude else []

    def _valid(norm_name: str) -> bool:
        return not any(ex in norm_name for ex in exclude_norm)

    for kw in keywords:
        kw_norm = _normalize_column_name(kw)
        for col, norm in normed_cols.items():
            if norm == kw_norm and _valid(norm):
                return col

    for kw in keywords:
        kw_norm = _normalize_column_name(kw)
        for col, norm in normed_cols.items():
            if norm.startswith(kw_norm) and _valid(norm):
                return col

    return default


def _looks_like_number_or_time(val: str) -> bool:
    s = str(val).strip()
    if not s:
        return False
    if re.fullmatch(r"[-+]?\d*(?:\.\d+)?(?:e[-+]?\d+)?", s):
        return True
    if re.fullmatch(r"\d{1,2}(?::\d{2}){1,2}(?:\.\d+)?", s):
        return True
    return False


def load_events(file_path, *, cache: DataCache | None = None):
    """Return event labels, times and optional frames from a table file or DataFrame."""

    if isinstance(file_path, pd.DataFrame):
        log.info("Loading events from DataFrame")
        df = file_path.copy()
        from_dataframe = True
        delimiter = ","
    else:
        log.info("Loading events from %s", file_path)
        with open(file_path, "r", encoding="utf-8-sig") as handle:
            sample = handle.read(1024)
            try:
                delimiter = csv.Sniffer().sniff(sample).delimiter
            except csv.Error:
                if "," in sample:
                    delimiter = ","
                elif "\t" in sample:
                    delimiter = "\t"
                else:
                    delimiter = ";"

        def _read_events(path: Path) -> pd.DataFrame:
            frame = pd.read_csv(path, delimiter=delimiter)
            if isinstance(frame.columns, pd.MultiIndex):
                frame.columns = [
                    " ".join(str(part) for part in col if pd.notna(part))
                    for col in frame.columns
                ]
            if any(_looks_like_number_or_time(c) for c in frame.columns):
                frame = pd.read_csv(path, delimiter=delimiter, header=None)
                frame.columns = [f"col{i}" for i in range(frame.shape[1])]
            return frame

        if cache is not None and DataCache is not None:
            df = cache.read_dataframe(file_path, loader=_read_events)
        else:
            df = _read_events(Path(file_path))
        from_dataframe = False

    df = _standardize_headers(df)

    if "EventLabel" in df.columns and df["EventLabel"].eq("-").all():
        possible_labels = df.index.astype(str)
        if any(l != "-" and not l.replace(".", "", 1).isdigit() for l in possible_labels):
            df = df.reset_index()
            df.rename(columns={"index": "EventLabel"}, inplace=True)

    label_candidates = [col for col in df.columns if not _is_numeric_or_time_series(df[col])]
    if label_candidates:
        fallback_label = label_candidates[0]
    elif len(df.columns) > 1:
        fallback_label = df.columns[1]
    else:
        fallback_label = df.columns[0]

    label_col = _find_column(df, ["label", "event", "name"], fallback_label, exclude=["time"])
    if label_col is None:
        label_col = fallback_label

    numeric_candidates = [
        col for col in df.columns if col != label_col and _is_numeric_or_time_series(df[col])
    ]
    if numeric_candidates:
        default_time = numeric_candidates[0]
    else:
        default_time = next((c for c in df.columns if c != label_col), df.columns[0])

    time_col = _find_column(df, ["time"], default_time)
    if time_col is None:
        time_col = default_time
    if time_col == label_col:
        time_col = next((c for c in df.columns if c != label_col), time_col)
    if time_col is None:
        raise ValueError("Could not determine a time column in events table")

    frame_col = _find_column(df, ["frame"])

    time_series = df[time_col]
    numeric = pd.to_numeric(time_series, errors="coerce")
    if numeric.notna().any():
        time_values = numeric.copy()
        missing = numeric.isna()
        if missing.any():
            td = pd.to_timedelta(time_series[missing], errors="coerce").dt.total_seconds()
            time_values.loc[missing] = td
    else:
        td = pd.to_timedelta(time_series, errors="coerce")
        time_values = td.dt.total_seconds()

    valid_mask = time_values.notna()
    if not valid_mask.all():
        df = df.loc[valid_mask].reset_index(drop=True)
        time_values = time_values.loc[valid_mask].reset_index(drop=True)
    else:
        time_values = time_values.reset_index(drop=True)

    labels = df[label_col].astype(str).reset_index(drop=True).tolist()
    times = time_values.astype(float).tolist()

    frames = None
    if frame_col and frame_col in df.columns:
        frame_series = df[frame_col].reset_index(drop=True)
        frames = frame_series.tolist()

    log.info("Loaded %d events", len(labels))
    return labels, times, frames


def _resolve_existing_case(folder: Path, candidate: Path) -> Path:
    try:
        for entry in folder.iterdir():
            if entry.name.lower() == candidate.name.lower():
                return entry
    except FileNotFoundError:  # pragma: no cover
        return candidate
    return candidate


def find_matching_event_file(trace_file: str) -> str | None:
    """Return the path to a matching event file if it exists."""

    trace_path = Path(trace_file)
    base = trace_path.stem
    folder = trace_path.parent

    patterns = [
        f"{base}_table.csv",
        f"{base}_Table.csv",
        f"{base}-table.csv",
        f"{base}-Table.csv",
        f"{base} table.csv",
        f"{base} Table.csv",
        f"{base} - table.csv",
        f"{base} - Table.csv",
        f"{base}_table.txt",
        f"{base}_Table.txt",
        f"{base}-table.txt",
        f"{base}-Table.txt",
        f"{base} table.txt",
        f"{base} Table.txt",
        f"{base} - table.txt",
        f"{base} - Table.txt",
    ]

    for pattern in patterns:
        candidate = folder / pattern
        if candidate.exists():
            resolved = _resolve_existing_case(folder, candidate)
            return str(resolved)
    return None


__all__ = ["load_events", "find_matching_event_file"]
