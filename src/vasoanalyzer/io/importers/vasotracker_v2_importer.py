from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

from .vasotracker_normalize import (
    _find_column,
    _float_or_none,
    _int_or_none,
    _nearest_time_index,
    _parse_time_seconds,
    _read_csv_sniff,
    _seconds_to_hms,
    _to_numeric_series,
    _to_string_series,
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


def _as_binary(values: np.ndarray, *, default: int = 0) -> np.ndarray:
    out = np.full(values.size, default, dtype=int)
    finite = np.isfinite(values)
    out[finite] = np.where(values[finite] > 0, 1, 0)
    return out


def _fallback_frame_numbers(frame_values: np.ndarray) -> np.ndarray:
    out = np.arange(frame_values.size, dtype=int)
    finite = np.isfinite(frame_values)
    out[finite] = np.rint(frame_values[finite]).astype(int)
    return out


def _prefer_value(primary: object, fallback: float | None) -> float | None:
    primary_value = _float_or_none(primary)
    if primary_value is not None:
        return primary_value
    return fallback


def _string_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return None
    return text


def import_vasotracker_v2(
    trace_csv_path: Path,
    *,
    table_csv_path: Path | None = None,
    normalize_time_to_zero: bool = False,
) -> tuple[list[TraceFrame], list[EventRow], ImportReport]:
    """Import VasoTracker v2 CSV files into canonical rows.

    Event rows preserve source table order.
    """

    warnings: list[str] = []
    errors: list[str] = []
    stats: dict[str, float | int | str] = {}

    trace_df = _read_csv_sniff(trace_csv_path)

    time_display_col = _select_column(trace_df, ("Time (s)", "Time", "Time_s"))
    time_exact_col = _select_column(trace_df, ("Time_s_exact", "TimeExact"))
    if time_display_col is None and time_exact_col is None:
        raise ValueError("Trace file must contain Time (s) or Time_s_exact")

    outer_col = _select_column(trace_df, ("Outer Diameter", "OD", "OuterDiam"), required=True)
    inner_col = _select_column(trace_df, ("Inner Diameter", "ID", "InnerDiam"), required=True)

    frame_col = _select_column(trace_df, ("FrameNumber", "Frame"))
    saved_col = _select_column(trace_df, ("Saved",))
    tiff_col = _select_column(trace_df, ("TiffPage", "TifPage"))
    table_marker_col = _select_column(trace_df, ("Table Marker", "TableMarker"))
    temperature_col = _select_column(trace_df, ("Temperature (oC)", "Temp", "Temperature"))
    pressure_1_col = _select_column(trace_df, ("Pressure 1 (mmHg)", "P1", "Pressure1"))
    pressure_2_col = _select_column(trace_df, ("Pressure 2 (mmHg)", "P2", "Pressure2"))
    avg_pressure_col = _select_column(trace_df, ("Avg Pressure (mmHg)", "Pavg", "AvgPressure"))
    set_pressure_col = _select_column(trace_df, ("Set Pressure (mmHg)", "SetPressure"))
    caliper_col = _select_column(trace_df, ("Caliper length", "Caliper"))
    outer_profiles_col = _select_column(trace_df, ("Outer Profiles",))
    inner_profiles_col = _select_column(trace_df, ("Inner Profiles",))
    outer_profiles_valid_col = _select_column(trace_df, ("Outer Profiles Valid",))
    inner_profiles_valid_col = _select_column(trace_df, ("Inner Profiles Valid",))

    time_display_values = _to_numeric_series(trace_df, time_display_col)
    time_exact_values = _to_numeric_series(trace_df, time_exact_col)
    if time_exact_col is None:
        time_exact_values = time_display_values.copy()
    if time_display_col is None:
        time_display_values = time_exact_values.copy()

    if normalize_time_to_zero and np.isfinite(time_exact_values).any():
        offset = float(time_exact_values[np.isfinite(time_exact_values)][0])
        time_exact_values = time_exact_values - offset
        time_display_values = time_display_values - offset
        stats["normalized_time_offset_s"] = offset
    else:
        stats["normalized_time_offset_s"] = 0.0

    outer_values = _to_numeric_series(trace_df, outer_col)
    inner_values = _to_numeric_series(trace_df, inner_col)
    temperature_values = _to_numeric_series(trace_df, temperature_col)
    pressure_1_values = _to_numeric_series(trace_df, pressure_1_col)
    pressure_2_values = _to_numeric_series(trace_df, pressure_2_col)
    avg_pressure_values = _to_numeric_series(trace_df, avg_pressure_col)
    set_pressure_values = _to_numeric_series(trace_df, set_pressure_col)
    caliper_values = _to_numeric_series(trace_df, caliper_col)

    if avg_pressure_col is None and pressure_1_col is not None and pressure_2_col is not None:
        with np.errstate(invalid="ignore"):
            stacked = np.vstack([pressure_1_values, pressure_2_values])
            avg_pressure_values = np.nanmean(stacked, axis=0)

    frame_values = _to_numeric_series(trace_df, frame_col)
    frame_numbers = _fallback_frame_numbers(frame_values)

    saved_values = _as_binary(_to_numeric_series(trace_df, saved_col), default=0)
    tiff_values = _to_numeric_series(trace_df, tiff_col)
    table_markers = _as_binary(_to_numeric_series(trace_df, table_marker_col), default=0)

    outer_profiles = _to_string_series(trace_df, outer_profiles_col, default="[]")
    inner_profiles = _to_string_series(trace_df, inner_profiles_col, default="[]")
    outer_profiles_valid = _to_string_series(trace_df, outer_profiles_valid_col, default="[]")
    inner_profiles_valid = _to_string_series(trace_df, inner_profiles_valid_col, default="[]")

    neg_inner = int(np.sum(inner_values < 0))
    neg_outer = int(np.sum(outer_values < 0))
    stats["negative_inner_diameter_count"] = neg_inner
    stats["negative_outer_diameter_count"] = neg_outer
    if neg_inner:
        warnings.append(f"negative_inner_diameter_count={neg_inner}")
    if neg_outer:
        warnings.append(f"negative_outer_diameter_count={neg_outer}")

    frame_to_index: dict[int, int] = {}
    for idx, frame_number in enumerate(frame_numbers.tolist()):
        frame_to_index.setdefault(int(frame_number), idx)

    table_candidate = table_csv_path or guess_table_csv_for_trace(trace_csv_path)
    if table_candidate is not None:
        stats["table_csv"] = str(table_candidate)

    events: list[EventRow] = []
    placed_count = 0
    unplaced_count = 0

    if table_candidate is not None:
        try:
            table_df = _read_csv_sniff(table_candidate)
            label_col = _select_column(table_df, ("Label", "Event", "EventLabel", "Name"))
            time_col = _select_column(table_df, ("Time", "Time (s)", "Timestamp"))
            frame_col_ev = _select_column(table_df, ("Frame", "FrameNumber"))
            od_col = _select_column(table_df, ("OD", "Outer Diameter"))
            od_ref_col = _select_column(table_df, ("%OD ref", "OD ref", "ODRef"))
            id_col = _select_column(table_df, ("ID", "Inner Diameter"))
            caliper_col_ev = _select_column(table_df, ("Caliper", "Caliper length"))
            pavg_col = _select_column(table_df, ("Pavg", "Avg Pressure (mmHg)"))
            p1_col = _select_column(table_df, ("P1", "Pressure 1 (mmHg)"))
            p2_col = _select_column(
                table_df,
                ("P2", "Pressure 2 (mmHg)", "Set Pressure (mmHg)"),
            )
            temp_col = _select_column(table_df, ("Temp", "Temperature (oC)"))

            if label_col is None and len(table_df.columns):
                label_col = str(table_df.columns[0])

            for event_idx, (_, row) in enumerate(table_df.iterrows(), start=1):
                label = str(row.get(label_col, "")).strip() if label_col is not None else ""
                raw_time = _parse_time_seconds(row.get(time_col)) if time_col is not None else None
                raw_frame = (
                    _int_or_none(row.get(frame_col_ev)) if frame_col_ev is not None else None
                )

                snap_idx: int | None = None
                if raw_frame is not None:
                    snap_idx = frame_to_index.get(raw_frame)
                    if snap_idx is None and raw_time is None:
                        warnings.append(f"unplaced_event_row={event_idx}: frame={raw_frame}")
                if snap_idx is None and raw_time is not None and math.isfinite(raw_time):
                    snap_idx = _nearest_time_index(time_exact_values, raw_time)

                if snap_idx is None:
                    unplaced_count += 1
                    warnings.append(f"unplaced_event_row={event_idx}")
                    events.append(
                        EventRow(
                            index=event_idx,
                            time_hms=_seconds_to_hms(raw_time),
                            frame_number=raw_frame if raw_frame is not None else -1,
                            label=label,
                            od_um=_float_or_none(row.get(od_col)) if od_col is not None else None,
                            od_ref_pct=_float_or_none(row.get(od_ref_col))
                            if od_ref_col is not None
                            else None,
                            id_um=_float_or_none(row.get(id_col)) if id_col is not None else None,
                            caliper=(
                                _float_or_none(row.get(caliper_col_ev))
                                if caliper_col_ev is not None
                                else None
                            ),
                            pavg_mmHg=(
                                _float_or_none(row.get(pavg_col)) if pavg_col is not None else None
                            ),
                            p1_mmHg=_float_or_none(row.get(p1_col)) if p1_col is not None else None,
                            p2_mmHg=_float_or_none(row.get(p2_col)) if p2_col is not None else None,
                            temp_C=_float_or_none(row.get(temp_col))
                            if temp_col is not None
                            else None,
                            raw_time_s=raw_time,
                            snap_delta_s=None,
                        )
                    )
                    continue

                placed_count += 1
                table_markers[snap_idx] = 1
                snapped_time = float(time_exact_values[snap_idx])

                events.append(
                    EventRow(
                        index=event_idx,
                        time_hms=_seconds_to_hms(snapped_time),
                        frame_number=int(frame_numbers[snap_idx]),
                        label=label,
                        od_um=_prefer_value(
                            row.get(od_col) if od_col is not None else None,
                            _float_or_none(outer_values[snap_idx]),
                        ),
                        od_ref_pct=_float_or_none(row.get(od_ref_col))
                        if od_ref_col is not None
                        else None,
                        id_um=_prefer_value(
                            row.get(id_col) if id_col is not None else None,
                            _float_or_none(inner_values[snap_idx]),
                        ),
                        caliper=_prefer_value(
                            row.get(caliper_col_ev) if caliper_col_ev is not None else None,
                            _float_or_none(caliper_values[snap_idx]),
                        ),
                        pavg_mmHg=_prefer_value(
                            row.get(pavg_col) if pavg_col is not None else None,
                            _float_or_none(avg_pressure_values[snap_idx]),
                        ),
                        p1_mmHg=_prefer_value(
                            row.get(p1_col) if p1_col is not None else None,
                            _float_or_none(pressure_1_values[snap_idx]),
                        ),
                        p2_mmHg=_prefer_value(
                            row.get(p2_col) if p2_col is not None else None,
                            _float_or_none(pressure_2_values[snap_idx]),
                        ),
                        temp_C=_prefer_value(
                            row.get(temp_col) if temp_col is not None else None,
                            _float_or_none(temperature_values[snap_idx]),
                        ),
                        raw_time_s=raw_time,
                        snap_delta_s=abs(snapped_time - raw_time)
                        if raw_time is not None
                        else None,
                    )
                )

        except Exception as exc:
            errors.append(
                f"table_parse_failed={Path(table_candidate).name}: {exc}. Imported trace only."
            )
            events = []

    stats["placed_event_count"] = placed_count
    stats["unplaced_event_count"] = unplaced_count

    frames: list[TraceFrame] = []
    for idx in range(len(trace_df.index)):
        frames.append(
            TraceFrame(
                time_s=float(time_display_values[idx]),
                time_hms=_seconds_to_hms(float(time_display_values[idx])),
                time_s_exact=float(time_exact_values[idx]),
                frame_number=int(frame_numbers[idx]),
                saved=int(saved_values[idx]),
                tiff_page=_int_or_none(tiff_values[idx]),
                outer_diameter_um=_float_or_none(outer_values[idx]),
                inner_diameter_um=_float_or_none(inner_values[idx]),
                table_marker=int(table_markers[idx]),
                temperature_C=_float_or_none(temperature_values[idx]),
                pressure_1_mmHg=_float_or_none(pressure_1_values[idx]),
                pressure_2_mmHg=_float_or_none(pressure_2_values[idx]),
                avg_pressure_mmHg=_float_or_none(avg_pressure_values[idx]),
                set_pressure_mmHg=_float_or_none(set_pressure_values[idx]),
                caliper_length=_float_or_none(caliper_values[idx]),
                outer_profiles=_string_or_none(outer_profiles[idx]),
                inner_profiles=_string_or_none(inner_profiles[idx]),
                outer_profiles_valid=_string_or_none(outer_profiles_valid[idx]),
                inner_profiles_valid=_string_or_none(inner_profiles_valid[idx]),
            )
        )

    report = ImportReport(
        source_format="vasotracker_v2",
        trace_rows=len(frames),
        event_rows=len(events),
        warnings=warnings,
        errors=errors,
        stats=stats,
    )
    return frames, events, report


__all__ = ["import_vasotracker_v2"]
