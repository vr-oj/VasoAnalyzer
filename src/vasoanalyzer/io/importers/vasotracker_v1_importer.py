from __future__ import annotations

import math
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

from .vasotracker_normalize import (
    _find_column,
    _float_or_none,
    _nearest_time_index,
    _parse_time_seconds,
    _read_csv_sniff,
    _seconds_to_hms,
    _to_numeric_series,
    guess_table_csv_for_trace,
)
from .vasotracker_v2_contract import EventRow, ImportReport, TraceFrame


def _select_column(
    df: pd.DataFrame,
    names: tuple[str, ...],
    *,
    required: bool = False,
) -> str | None:
    return _find_column(df, names, required=required)


def _safe_average(p1: np.ndarray, p2: np.ndarray) -> np.ndarray:
    stacked = np.vstack([p1, p2])
    with np.errstate(invalid="ignore"):
        return np.nanmean(stacked, axis=0)


def _event_columns_v1(df: pd.DataFrame) -> tuple[str, str | None]:
    label_col = _select_column(
        df,
        (
            "Label",
            "EventLabel",
            "Event",
            "Name",
            "Manipulation",
        ),
    )
    if label_col is None:
        label_col = str(df.columns[0]) if len(df.columns) else "Label"

    time_col = _select_column(
        df,
        (
            "Time",
            "Timestamp",
            "Time (s)",
            "Time_s",
            "t",
        ),
    )

    if time_col is None:
        for col in df.columns:
            if str(col) == str(label_col):
                continue
            parsed = [
                _parse_time_seconds(value)
                for value in df[str(col)].head(min(20, len(df.index))).tolist()
            ]
            valid = [value for value in parsed if value is not None and math.isfinite(value)]
            if valid and (len(valid) / max(1, len(parsed))) >= 0.3:
                time_col = str(col)
                break

    return str(label_col), str(time_col) if time_col is not None else None


def import_vasotracker_v1(
    trace_csv_path: Path,
    *,
    table_csv_path: Path | None = None,
    normalize_time_to_zero: bool = True,
    generate_frame_numbers: Literal["row_index"] = "row_index",
    set_table_markers: bool = True,
) -> tuple[list[TraceFrame], list[EventRow], ImportReport]:
    """Import VasoTracker v1 CSV files into canonical v2-style rows.

    Event rows preserve source table order.
    """

    warnings: list[str] = []
    errors: list[str] = []
    stats: dict[str, float | int | str] = {}

    if generate_frame_numbers != "row_index":
        raise ValueError("Only generate_frame_numbers='row_index' is supported")

    trace_df = _read_csv_sniff(trace_csv_path)

    time_col = _select_column(trace_df, ("Time", "Time (s)", "Time_s", "t"), required=True)
    outer_col = _select_column(
        trace_df,
        ("Outer Diameter", "OD", "OuterDiam"),
        required=True,
    )
    inner_col = _select_column(
        trace_df,
        ("Inner Diameter", "ID", "InnerDiam", "Diameter"),
        required=True,
    )

    temperature_col = _select_column(trace_df, ("Temperature (oC)", "Temp", "Temperature"))
    pressure_1_col = _select_column(trace_df, ("Pressure 1 (mmHg)", "P1", "Pressure1"))
    pressure_2_col = _select_column(trace_df, ("Pressure 2 (mmHg)", "P2", "Pressure2"))
    avg_pressure_col = _select_column(trace_df, ("Avg Pressure (mmHg)", "Pavg", "AvgPressure"))
    caliper_col = _select_column(trace_df, ("Caliper length", "Caliper", "CaliperLength"))

    time_values = _to_numeric_series(trace_df, time_col)
    outer_values = _to_numeric_series(trace_df, outer_col)
    inner_values = _to_numeric_series(trace_df, inner_col)
    temperature_values = _to_numeric_series(trace_df, temperature_col)
    pressure_1_values = _to_numeric_series(trace_df, pressure_1_col)
    pressure_2_values = _to_numeric_series(trace_df, pressure_2_col)
    caliper_values = _to_numeric_series(trace_df, caliper_col)

    avg_pressure_values = _to_numeric_series(trace_df, avg_pressure_col)
    if avg_pressure_col is None and pressure_1_col is not None and pressure_2_col is not None:
        avg_pressure_values = _safe_average(pressure_1_values, pressure_2_values)

    if np.isfinite(time_values).any():
        first_time = float(time_values[np.isfinite(time_values)][0])
    else:
        first_time = 0.0
    if normalize_time_to_zero:
        time_exact_values = time_values - first_time
        stats["normalized_time_offset_s"] = first_time
    else:
        time_exact_values = time_values.copy()
        stats["normalized_time_offset_s"] = 0.0

    time_display_values = time_exact_values.copy()
    frame_numbers = np.arange(len(trace_df.index), dtype=int)
    table_markers = np.zeros(len(trace_df.index), dtype=int)

    neg_inner = int(np.sum(inner_values < 0))
    neg_outer = int(np.sum(outer_values < 0))
    stats["negative_inner_diameter_count"] = neg_inner
    stats["negative_outer_diameter_count"] = neg_outer
    stats["frame_number_rule"] = "row_index"

    if neg_inner:
        warnings.append(f"negative_inner_diameter_count={neg_inner}")
    if neg_outer:
        warnings.append(f"negative_outer_diameter_count={neg_outer}")

    table_candidate = table_csv_path or guess_table_csv_for_trace(trace_csv_path)
    if table_candidate is not None:
        stats["table_csv"] = str(table_candidate)

    events: list[EventRow] = []
    unplaced_count = 0
    placed_count = 0

    if table_candidate is not None:
        try:
            table_df = _read_csv_sniff(table_candidate)
            label_col, time_col_ev = _event_columns_v1(table_df)

            for row_idx, (_, row) in enumerate(table_df.iterrows(), start=1):
                label = str(row.get(label_col, "")).strip()
                raw_time = _parse_time_seconds(row.get(time_col_ev)) if time_col_ev else None
                if raw_time is not None and normalize_time_to_zero:
                    raw_time -= first_time

                snap_idx: int | None = None
                if raw_time is not None and math.isfinite(raw_time):
                    snap_idx = _nearest_time_index(time_exact_values, raw_time)

                if snap_idx is None:
                    unplaced_count += 1
                    warnings.append(f"unplaced_event_row={row_idx}")
                    events.append(
                        EventRow(
                            index=row_idx,
                            time_hms=_seconds_to_hms(raw_time),
                            frame_number=-1,
                            label=label,
                            od_um=None,
                            od_ref_pct=None,
                            id_um=None,
                            caliper=None,
                            pavg_mmHg=None,
                            p1_mmHg=None,
                            p2_mmHg=None,
                            temp_C=None,
                            raw_time_s=raw_time,
                            snap_delta_s=None,
                        )
                    )
                    continue

                if set_table_markers:
                    table_markers[snap_idx] = 1
                placed_count += 1

                snapped_time = float(time_exact_values[snap_idx])
                event = EventRow(
                    index=row_idx,
                    time_hms=_seconds_to_hms(snapped_time),
                    frame_number=int(frame_numbers[snap_idx]),
                    label=label,
                    od_um=_float_or_none(outer_values[snap_idx]),
                    od_ref_pct=None,
                    id_um=_float_or_none(inner_values[snap_idx]),
                    caliper=_float_or_none(caliper_values[snap_idx]),
                    pavg_mmHg=_float_or_none(avg_pressure_values[snap_idx]),
                    p1_mmHg=_float_or_none(pressure_1_values[snap_idx]),
                    p2_mmHg=_float_or_none(pressure_2_values[snap_idx]),
                    temp_C=_float_or_none(temperature_values[snap_idx]),
                    raw_time_s=raw_time,
                    snap_delta_s=abs(snapped_time - raw_time) if raw_time is not None else None,
                )
                events.append(event)

        except Exception as exc:
            errors.append(
                f"table_parse_failed={Path(table_candidate).name}: {exc}. Imported trace only."
            )
            events = []
            table_markers[:] = 0

    stats["placed_event_count"] = placed_count
    stats["unplaced_event_count"] = unplaced_count

    frames: list[TraceFrame] = []
    for idx in range(len(trace_df.index)):
        frame = TraceFrame(
            time_s=float(time_display_values[idx]),
            time_hms=_seconds_to_hms(float(time_display_values[idx])),
            time_s_exact=float(time_exact_values[idx]),
            frame_number=int(frame_numbers[idx]),
            saved=0,
            tiff_page=None,
            outer_diameter_um=_float_or_none(outer_values[idx]),
            inner_diameter_um=_float_or_none(inner_values[idx]),
            table_marker=int(table_markers[idx]),
            temperature_C=_float_or_none(temperature_values[idx]),
            pressure_1_mmHg=_float_or_none(pressure_1_values[idx]),
            pressure_2_mmHg=_float_or_none(pressure_2_values[idx]),
            avg_pressure_mmHg=_float_or_none(avg_pressure_values[idx]),
            set_pressure_mmHg=None,
            caliper_length=_float_or_none(caliper_values[idx]),
            outer_profiles="[]",
            inner_profiles="[]",
            outer_profiles_valid="[]",
            inner_profiles_valid="[]",
        )
        frames.append(frame)

    report = ImportReport(
        source_format="vasotracker_v1",
        trace_rows=len(frames),
        event_rows=len(events),
        warnings=warnings,
        errors=errors,
        stats=stats,
    )
    return frames, events, report


__all__ = ["import_vasotracker_v1"]
