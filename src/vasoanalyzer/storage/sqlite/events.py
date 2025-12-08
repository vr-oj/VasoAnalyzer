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
        elif (
            norm in {"od", "outerdiam", "outerdiameter"} and "od" not in mapping.values()
        ):
            mapping[col] = "od"
        elif (
            norm in {"id", "innerdiam", "innerdiameter", "diambefore"}
            and "id_diam" not in mapping.values()
        ):
            mapping[col] = "id_diam"
        elif (
            norm in {"caliper", "caliperlength"} and "caliper" not in mapping.values()
        ):
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
    for _, row in df_local.iterrows():
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

        rows.append(
            (
                dataset_id,
                float(row.get("t_seconds")),
                row.get("label"),
                nullable_int(row.get("frame")),
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

    query = [
        "SELECT t_seconds, label, frame, p_avg, p1, p2, temp, extra_json",
        "FROM event",
        "WHERE dataset_id = ?",
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

        for payload in df["extra_json"]:
            extra_dict = json.loads(payload) if isinstance(payload, str) and payload else {}

            # CRITICAL FIX: Extract review_state and add as top-level column
            review_state = extra_dict.pop("review_state", "UNREVIEWED")
            review_states.append(review_state)

            extras.append(extra_dict)

        df = df.drop(columns=["extra_json"])
        df["review_state"] = review_states  # Add as top-level column
        df["extra"] = extras
    else:
        # If no extra_json column exists, add default review_state
        if not df.empty:
            df["review_state"] = "UNREVIEWED"

    return df
