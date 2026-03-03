"""
Event table persistence helpers for SQLite projects.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Sequence

import pandas as pd

from vasoanalyzer.storage.sqlite import traces as _traces

__all__ = [
    "match_event_columns",
    "nullable_int",
    "prepare_event_rows",
    "fetch_events_dataframe",
]


def match_event_columns(columns: Sequence[str]) -> dict[str, str]:
    """Build a mapping from arbitrary column names to canonical event fields."""

    mapping: dict[str, str] = {}
    for col in columns:
        norm = _traces.normalize_label(col)
        if (
            norm in {"times", "time", "tseconds", "timestamp"}
            and "t_seconds" not in mapping.values()
        ):
            mapping[col] = "t_seconds"
        elif norm in {"event", "label"} and "label" not in mapping.values():
            mapping[col] = "label"
        elif norm in {"frame", "frames"} and "frame" not in mapping.values():
            mapping[col] = "frame"
        elif norm in {"pavg", "pressureavg"} and "p_avg" not in mapping.values():
            mapping[col] = "p_avg"
        elif norm == "p1" and "p1" not in mapping.values():
            mapping[col] = "p1"
        elif norm == "p2" and "p2" not in mapping.values():
            mapping[col] = "p2"
        elif norm in {"temp", "temperature"} and "temp" not in mapping.values():
            mapping[col] = "temp"
        # VasoTracker event table columns
        elif norm in {"od", "outerdiam", "outerdiameter"} and "od" not in mapping.values():
            mapping[col] = "od"
        elif (
            norm in {"id", "innerdiam", "innerdiameter", "diambefore"}
            and "id_diam" not in mapping.values()
        ):
            mapping[col] = "id_diam"
        elif norm in {"caliper", "caliperlength"} and "caliper" not in mapping.values():
            mapping[col] = "caliper"
        elif (
            norm in {"odref", "odrefpct", "percentodref", "odreference"}
            and "od_ref_pct" not in mapping.values()
        ):
            mapping[col] = "od_ref_pct"
    return mapping


def nullable_int(value) -> int | None:
    """Return an int or ``None`` while tolerating NaN-like values."""

    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def prepare_event_rows(dataset_id: int, df: pd.DataFrame | None) -> Iterable[tuple]:
    """Normalize events DataFrame into rows suitable for insertion."""

    if df is None or df.empty:
        return []

    df_local = df.copy()
    rename_map = match_event_columns(df_local.columns)
    if rename_map:
        df_local = df_local.rename(columns=rename_map)

    if "t_seconds" not in df_local.columns or "label" not in df_local.columns:
        raise ValueError("Events DataFrame must include time and label columns")

    time_raw = df_local["t_seconds"].copy()
    df_local["t_seconds"] = pd.to_numeric(time_raw, errors="coerce")
    if df_local["t_seconds"].isna().all():
        # Attempt to parse timestamps like HH:MM:SS and convert to seconds
        td = pd.to_timedelta(time_raw, errors="coerce")
        if not td.isna().all():
            df_local["t_seconds"] = td.dt.total_seconds()

    df_local = df_local.dropna(subset=["t_seconds"])
    df_local["label"] = df_local["label"].astype(str)

    for col in ("frame", "p_avg", "p1", "p2", "temp"):
        if col in df_local.columns:
            df_local[col] = pd.to_numeric(df_local[col], errors="coerce")

    rows = []
    # CRITICAL FIX (Bug #1): Exclude review_state from extra_cols since it needs special handling
    extra_cols = [
        c
        for c in df_local.columns
        if c not in {"t_seconds", "label", "frame", "p_avg", "p1", "p2", "temp", "review_state"}
    ]
    for idx, row in df_local.iterrows():
        extra_json = None
        payload = {}

        # CRITICAL FIX: Always include review_state in extra_json
        review_state = row.get("review_state", "UNREVIEWED")
        if pd.notna(review_state):
            payload["review_state"] = str(review_state)
        else:
            payload["review_state"] = "UNREVIEWED"

        # Include other extra columns
        if extra_cols:
            for c in extra_cols:
                val = row.get(c)
                if pd.notna(val):
                    payload[c] = val

        if payload:
            extra_json = json.dumps(payload, ensure_ascii=False)

        t_us = int(round(float(row.get("t_seconds")) * 1_000_000))
        source_frame = nullable_int(row.get("frame"))
        rows.append(
            (
                dataset_id,
                float(row.get("t_seconds")),
                t_us,
                row.get("label"),
                nullable_int(row.get("frame")),
                source_frame,
                idx,
                str(time_raw.get(idx)) if "t_seconds" in df_local.columns else None,
                _traces.nullable_float(row.get("p_avg")),
                _traces.nullable_float(row.get("p1")),
                _traces.nullable_float(row.get("p2")),
                _traces.nullable_float(row.get("temp")),
                extra_json,
            )
        )
    return rows


def fetch_events_dataframe(
    conn: sqlite3.Connection,
    dataset_id: int,
    t0: float | None = None,
    t1: float | None = None,
) -> pd.DataFrame:
    """Return events for ``dataset_id`` optionally filtered to ``[t0, t1]``."""

    # Check which columns exist to handle both old and new schemas gracefully.
    existing_cols = {
        row[1]
        for row in conn.execute("PRAGMA table_info(event)").fetchall()
    }
    extra_select_cols = [
        c for c in ("od", "id_diam") if c in existing_cols
    ]
    select_cols = "t_seconds, t_us, label, frame, p_avg, p1, p2, temp"
    if extra_select_cols:
        select_cols += ", " + ", ".join(extra_select_cols)
    select_cols += ", extra_json"

    query = [
        f"SELECT {select_cols}",
        "FROM event",
        "WHERE dataset_id = ?",
        "AND deleted_utc IS NULL",
    ]
    params: list[object] = [dataset_id]
    if t0 is not None:
        query.append("AND t_seconds >= ?")
        params.append(float(t0))
    if t1 is not None:
        query.append("AND t_seconds <= ?")
        params.append(float(t1))
    query.append("ORDER BY t_seconds ASC")

    df = pd.read_sql_query(" ".join(query), conn, params=params)
    if not df.empty and "extra_json" in df.columns:
        extras = []
        review_states = []  # CRITICAL FIX (Bug #1): Extract review states separately
        extra_id_list = []
        extra_od_list = []

        for idx_row, payload in enumerate(df["extra_json"]):
            extra_dict = json.loads(payload) if isinstance(payload, str) and payload else {}

            # CRITICAL FIX: Extract review_state and add as top-level column
            review_state = extra_dict.pop("review_state", "UNREVIEWED")
            review_states.append(review_state)

            # Extract stored ID/OD measurements from extra_json for legacy events that
            # didn't populate the dedicated od/id_diam columns.
            extra_id_list.append(extra_dict.get("ID (µm)"))
            extra_od_list.append(extra_dict.get("OD (µm)"))

            extras.append(extra_dict)

        df = df.drop(columns=["extra_json"])
        df["review_state"] = review_states  # Add as top-level column
        df["extra"] = extras

        # Merge dedicated columns with extra_json fallback: prefer dedicated columns when set
        if "id_diam" in df.columns:
            fallback_id = pd.Series(extra_id_list, index=df.index, dtype=object)
            df["id_diam"] = df["id_diam"].combine_first(fallback_id)
        else:
            df["id_diam"] = pd.Series(extra_id_list, index=df.index, dtype=object)

        if "od" in df.columns:
            fallback_od = pd.Series(extra_od_list, index=df.index, dtype=object)
            df["od"] = df["od"].combine_first(fallback_od)
        else:
            df["od"] = pd.Series(extra_od_list, index=df.index, dtype=object)
    else:
        # If no extra_json column exists, add default review_state
        if not df.empty:
            df["review_state"] = "UNREVIEWED"

    return df
