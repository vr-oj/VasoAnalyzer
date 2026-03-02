from __future__ import annotations

import csv
import math
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .vasotracker_v2_contract import (
    EVENT_V2_TABLE_COLUMNS,
    TRACE_V2_COLUMNS,
    EventRow,
    TraceFrame,
)


def _read_csv_sniff(path: Path) -> pd.DataFrame:
    with path.open("r", encoding="utf-8-sig") as handle:
        sample = handle.read(4096)
    try:
        delimiter = csv.Sniffer().sniff(sample).delimiter
    except csv.Error:
        if "\t" in sample and "," not in sample:
            delimiter = "\t"
        elif ";" in sample and "," not in sample:
            delimiter = ";"
        else:
            delimiter = ","
    return pd.read_csv(path, delimiter=delimiter, encoding="utf-8-sig")


def _normalize_column_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def _find_column(
    df: pd.DataFrame,
    candidates: tuple[str, ...],
    *,
    required: bool = False,
) -> str | None:
    norm_map = {str(col): _normalize_column_name(str(col)) for col in df.columns}

    for candidate in candidates:
        target = _normalize_column_name(candidate)
        for original, norm in norm_map.items():
            if norm == target:
                return original

    for candidate in candidates:
        target = _normalize_column_name(candidate)
        for original, norm in norm_map.items():
            if norm.startswith(target):
                return original

    if required:
        raise ValueError(
            f"Missing required column. Expected one of {candidates}, found {list(df.columns)}"
        )
    return None


def _to_numeric_series(df: pd.DataFrame, column: str | None) -> np.ndarray:
    if column is None or column not in df.columns:
        return np.full(len(df.index), np.nan, dtype=float)
    values = pd.to_numeric(df[column], errors="coerce")
    return values.to_numpy(dtype=float)


def _to_string_series(df: pd.DataFrame, column: str | None, *, default: str = "") -> np.ndarray:
    if column is None or column not in df.columns:
        return np.full(len(df.index), default, dtype=object)
    series = df[column].astype(str).replace({"nan": default, "None": default})
    return series.to_numpy(dtype=object)


def _first_finite(values: np.ndarray) -> float | None:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return None
    return float(finite[0])


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return int(round(number))


def _parse_time_seconds(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float, np.number)):
        number = float(value)
        return number if math.isfinite(number) else None

    text = str(value).strip()
    if not text:
        return None
    if text.lower() in {"nan", "none", "null", "na", "n/a"}:
        return None

    text_num = text.replace(",", ".")
    try:
        number = float(text_num)
    except ValueError:
        number = None
    if number is not None and math.isfinite(number):
        return float(number)

    parts = text.split(":")
    if len(parts) not in {2, 3}:
        return None
    try:
        if len(parts) == 3:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = float(parts[2])
        else:
            hours = 0
            minutes = int(parts[0])
            seconds = float(parts[1])
    except ValueError:
        return None
    total = (hours * 3600.0) + (minutes * 60.0) + seconds
    return float(total) if math.isfinite(total) else None


def _seconds_to_hms(seconds: float | None) -> str:
    if seconds is None or not math.isfinite(seconds):
        return ""
    sign = "-" if seconds < 0 else ""
    total = int(round(abs(seconds)))
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    return f"{sign}{hours:02d}:{minutes:02d}:{secs:02d}"


def _nearest_time_index(trace_times: np.ndarray, event_time_s: float) -> int | None:
    """Return nearest trace index for ``event_time_s``; ties prefer lower index."""

    if trace_times.size == 0 or not math.isfinite(event_time_s):
        return None
    finite_idx = np.flatnonzero(np.isfinite(trace_times))
    if finite_idx.size == 0:
        return None
    distances = np.abs(trace_times[finite_idx] - event_time_s)
    nearest_pos = int(np.argmin(distances))
    return int(finite_idx[nearest_pos])


def _resolve_case_insensitive(folder: Path, candidate_name: str) -> Path | None:
    try:
        for entry in folder.iterdir():
            if entry.name.lower() == candidate_name.lower():
                return entry
    except FileNotFoundError:
        return None
    return None


def guess_table_csv_for_trace(trace_csv_path: Path) -> Path | None:
    """
    v1: foo.csv -> try:
        foo - Table.csv
        foo- Table.csv
        foo Table.csv
    v2: foo.csv -> try:
        foo_table.csv
        foo-table.csv
    """

    base = trace_csv_path.stem
    folder = trace_csv_path.parent
    candidates = (
        f"{base} - Table.csv",
        f"{base}- Table.csv",
        f"{base} Table.csv",
        f"{base}_table.csv",
        f"{base}-table.csv",
    )
    for candidate in candidates:
        matched = _resolve_case_insensitive(folder, candidate)
        if matched is not None and matched.exists():
            return matched
    return None


def trace_frames_to_dataframe(frames: list[TraceFrame]) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for frame in frames:
        records.append(
            {
                "Time (s)": frame.time_s,
                "Time (hh:mm:ss)": frame.time_hms,
                "Time_s_exact": frame.time_s_exact,
                "FrameNumber": frame.frame_number,
                "Saved": frame.saved,
                "TiffPage": frame.tiff_page,
                "Outer Diameter": frame.outer_diameter_um,
                "Inner Diameter": frame.inner_diameter_um,
                "Table Marker": frame.table_marker,
                "Temperature (oC)": frame.temperature_C,
                "Pressure 1 (mmHg)": frame.pressure_1_mmHg,
                "Pressure 2 (mmHg)": frame.pressure_2_mmHg,
                "Avg Pressure (mmHg)": frame.avg_pressure_mmHg,
                "Set Pressure (mmHg)": frame.set_pressure_mmHg,
                "Caliper length": frame.caliper_length,
                "Outer Profiles": frame.outer_profiles,
                "Inner Profiles": frame.inner_profiles,
                "Outer Profiles Valid": frame.outer_profiles_valid,
                "Inner Profiles Valid": frame.inner_profiles_valid,
            }
        )

    if not records:
        return pd.DataFrame(columns=list(TRACE_V2_COLUMNS))
    return pd.DataFrame.from_records(records, columns=list(TRACE_V2_COLUMNS))


def event_rows_to_dataframe(events: list[EventRow]) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for event in events:
        records.append(
            {
                "#": event.index,
                "Time": event.time_hms,
                "Frame": event.frame_number,
                "Label": event.label,
                "OD": event.od_um,
                "%OD ref": event.od_ref_pct,
                "ID": event.id_um,
                "Caliper": event.caliper,
                "Pavg": event.pavg_mmHg,
                "P1": event.p1_mmHg,
                "P2": event.p2_mmHg,
                "Temp": event.temp_C,
            }
        )

    if not records:
        return pd.DataFrame(columns=list(EVENT_V2_TABLE_COLUMNS))
    return pd.DataFrame.from_records(records, columns=list(EVENT_V2_TABLE_COLUMNS))


def event_rows_to_legacy_payload(
    events: list[EventRow],
) -> tuple[list[str], list[float], list[int | None], list[float | None], list[float | None]]:
    labels: list[str] = []
    times: list[float] = []
    frames: list[int | None] = []
    diam: list[float | None] = []
    od_diam: list[float | None] = []

    for event in events:
        labels.append(event.label)
        event_time = event.raw_time_s
        if event_time is None:
            event_time = _parse_time_seconds(event.time_hms)
        times.append(float(event_time) if event_time is not None else float("nan"))
        frames.append(event.frame_number if event.frame_number >= 0 else None)
        diam.append(event.id_um)
        od_diam.append(event.od_um)

    return labels, times, frames, diam, od_diam


def export_trace_as_v2_csv(frames: list[TraceFrame], out_csv_path: Path) -> None:
    out_csv_path.parent.mkdir(parents=True, exist_ok=True)
    df = trace_frames_to_dataframe(frames)
    df.to_csv(out_csv_path, index=False)


def export_events_as_v2_table_csv(events: list[EventRow], out_csv_path: Path) -> None:
    out_csv_path.parent.mkdir(parents=True, exist_ok=True)
    df = event_rows_to_dataframe(events)
    df.to_csv(out_csv_path, index=False)


__all__ = [
    "event_rows_to_dataframe",
    "event_rows_to_legacy_payload",
    "export_events_as_v2_table_csv",
    "export_trace_as_v2_csv",
    "guess_table_csv_for_trace",
    "trace_frames_to_dataframe",
]
