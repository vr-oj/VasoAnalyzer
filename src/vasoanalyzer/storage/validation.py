"""Dataset integrity signatures and validation helpers."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_SIGNATURE_VERSION = 1

__all__ = [
    "compute_events_signature",
    "compute_trace_signature",
    "quick_validate_project",
    "deep_validate_dataset",
    "update_dataset_signatures",
]


def _stable_hash(obj: Any) -> str:
    payload = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_events_signature(conn: sqlite3.Connection, dataset_id: int) -> str:
    """Compute a deterministic signature for active events."""

    rows = conn.execute(
        """
        SELECT t_us, t_seconds, label, source_row, source_frame
          FROM event
         WHERE dataset_id = ?
           AND (deleted_utc IS NULL)
         ORDER BY t_us ASC, id ASC
        """,
        (dataset_id,),
    ).fetchall()

    normalized = []
    for t_us, t_seconds, label, source_row, source_frame in rows:
        ts = int(t_us) if t_us is not None else int(round(float(t_seconds) * 1_000_000))
        normalized.append(
            [
                ts,
                str(label) if label is not None else "",
                int(source_row) if source_row is not None else None,
                int(source_frame) if source_frame is not None else None,
            ]
        )
    return _stable_hash(normalized)


def compute_trace_signature(conn: sqlite3.Connection, dataset_id: int, *, sample_k: int = 8) -> str:
    """Compute a signature for the trace time axis."""

    times = [
        float(row[0])
        for row in conn.execute(
            "SELECT t_seconds FROM trace WHERE dataset_id = ? ORDER BY t_seconds ASC",
            (dataset_id,),
        ).fetchall()
    ]
    if not times:
        return _stable_hash({"samples": [], "dt": None})

    t_us = [int(round(t * 1_000_000)) for t in times]
    n = len(t_us)
    sample_prefix = t_us[:sample_k]
    sample_suffix = t_us[-sample_k:] if n > sample_k else []

    if n > 1:
        deltas = [b - a for a, b in zip(t_us[:-1], t_us[1:])]
        median_dt = sorted(deltas)[len(deltas) // 2]
        min_dt = min(deltas)
        max_dt = max(deltas)
    else:
        median_dt = min_dt = max_dt = 0

    payload = {
        "n": n,
        "prefix": sample_prefix,
        "suffix": sample_suffix,
        "median_dt": median_dt,
        "min_dt": min_dt,
        "max_dt": max_dt,
    }
    return _stable_hash(payload)


def update_dataset_signatures(conn: sqlite3.Connection, dataset_id: int) -> dict[str, str]:
    """Compute and persist event/trace signatures for a dataset."""

    events_sig = compute_events_signature(conn, dataset_id)
    trace_sig = compute_trace_signature(conn, dataset_id)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        UPDATE dataset
           SET events_signature = ?,
               trace_signature = ?,
               signature_version = ?,
               last_validated_utc = ?,
               validation_status = 'ok',
               validation_error = NULL
         WHERE id = ?
        """,
        (events_sig, trace_sig, DEFAULT_SIGNATURE_VERSION, now, dataset_id),
    )
    conn.commit()
    return {"events_signature": events_sig, "trace_signature": trace_sig}


def _duplicate_signature_issues(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Detect duplicate event signatures across datasets with divergent sources."""

    issues: list[dict[str, Any]] = []
    rows = conn.execute(
        """
        SELECT id, events_signature, trace_source_fingerprint, events_source_fingerprint
          FROM dataset
         WHERE events_signature IS NOT NULL
        """
    ).fetchall()
    sig_map: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        sig = row[1]
        sig_map.setdefault(sig, []).append(row)

    for sig, datasets in sig_map.items():
        if len(datasets) < 2:
            continue
        fingerprints = {
            (d[2] or "", d[3] or "") for d in datasets
        }
        if len(fingerprints) > 1:
            issues.append(
                {
                    "kind": "duplicate_events_signature",
                    "signature": sig,
                    "dataset_ids": [int(d[0]) for d in datasets],
                    "detail": "Same events_signature across datasets with different sources",
                }
            )
    return issues


def quick_validate_project(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """
    Recompute signatures and flag drift/duplication.

    Returns a list of validation issues; also updates dataset validation fields.
    """

    issues: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc).isoformat()
    datasets = conn.execute(
        "SELECT id, events_signature, trace_signature FROM dataset ORDER BY id"
    ).fetchall()
    for row in datasets:
        ds_id = int(row[0])
        stored_events = row[1]
        stored_trace = row[2]
        computed_events = compute_events_signature(conn, ds_id)
        computed_trace = compute_trace_signature(conn, ds_id)

        status = "ok"
        error_msg = None
        if stored_events and stored_events != computed_events:
            status = "error"
            error_msg = "events_signature drift detected"
            issues.append(
                {
                    "kind": "events_signature_drift",
                    "dataset_id": ds_id,
                    "stored": stored_events,
                    "computed": computed_events,
                }
            )
        if stored_trace and stored_trace != computed_trace:
            # Keep the highest severity
            status = "error" if status != "error" else status
            error_msg = error_msg or "trace_signature drift detected"
            issues.append(
                {
                    "kind": "trace_signature_drift",
                    "dataset_id": ds_id,
                    "stored": stored_trace,
                    "computed": computed_trace,
                }
            )

        conn.execute(
            """
            UPDATE dataset
               SET events_signature = ?,
                   trace_signature = ?,
                   signature_version = ?,
                   last_validated_utc = ?,
                   validation_status = ?,
                   validation_error = ?
             WHERE id = ?
            """,
            (
                computed_events,
                computed_trace,
                DEFAULT_SIGNATURE_VERSION,
                now,
                status,
                error_msg,
                ds_id,
            ),
        )

    # Duplicate detection across datasets
    dup_issues = _duplicate_signature_issues(conn)
    issues.extend(dup_issues)
    if dup_issues:
        affected = {ds_id for issue in dup_issues for ds_id in issue.get("dataset_ids", [])}
        for ds_id in affected:
            conn.execute(
                """
                UPDATE dataset
                   SET validation_status = 'error',
                       validation_error = COALESCE(validation_error, 'duplicate events_signature')
                 WHERE id = ?
                """,
                (ds_id,),
            )

    conn.commit()
    return issues


def deep_validate_dataset(conn: sqlite3.Connection, dataset_id: int) -> dict[str, Any]:
    """
    Placeholder for deep validation.

    This stub recalculates signatures and returns residuals of zero to
    integrate with the UI without performing expensive raw checks.
    """

    sigs = update_dataset_signatures(conn, dataset_id)
    return {
        "dataset_id": dataset_id,
        "status": "ok",
        "events_signature": sigs["events_signature"],
        "trace_signature": sigs["trace_signature"],
        "residuals": {"median_abs_us": 0, "max_abs_us": 0},
    }
