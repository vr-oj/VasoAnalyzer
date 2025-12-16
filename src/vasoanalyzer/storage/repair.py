"""Dataset repair helpers that rebuild events from raw sources."""

from __future__ import annotations

import json
import logging
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from vasoanalyzer.storage import validation as _validation
from vasoanalyzer.storage.sqlite import events as _events

log = logging.getLogger(__name__)

__all__ = ["record_event_audit", "repair_dataset_from_raw", "soft_delete_events"]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_event_audit(
    conn: sqlite3.Connection,
    dataset_id: int,
    *,
    event_id: int | None,
    action: str,
    old: dict[str, Any] | None = None,
    new: dict[str, Any] | None = None,
    source: str = "ui",
) -> None:
    """Append an audit log entry."""

    conn.execute(
        """
        INSERT INTO event_audit(dataset_id, event_id, action, old_json, new_json, source, utc_ts)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            dataset_id,
            event_id,
            action,
            json.dumps(old, ensure_ascii=False) if old is not None else None,
            json.dumps(new, ensure_ascii=False) if new is not None else None,
            source,
            _utc_now(),
        ),
    )


def soft_delete_events(
    conn: sqlite3.Connection,
    dataset_id: int,
    event_ids: list[int],
    *,
    reason: str = "user",
    deleted_by: str = "ui",
) -> None:
    """Soft-delete events by id and record audit entries."""

    if not event_ids:
        return
    now = _utc_now()
    existing = {
        row["id"]: row
        for row in conn.execute(
            "SELECT id, t_us, label, source_row FROM event WHERE id IN ({seq}) AND dataset_id = ?".format(
                seq=",".join("?" for _ in event_ids)
            ),
            [*event_ids, dataset_id],
        ).fetchall()
    }
    conn.executemany(
        """
        UPDATE event
           SET deleted_utc = ?, deleted_reason = ?, deleted_by = ?
         WHERE id = ? AND dataset_id = ?
        """,
        [(now, reason, deleted_by, eid, dataset_id) for eid in event_ids],
    )
    for eid in event_ids:
        payload_row = existing.get(eid)
        record_event_audit(
            conn,
            dataset_id,
            event_id=eid,
            action="delete",
            old={
                "id": eid,
                "t_us": payload_row["t_us"] if payload_row else None,
                "label": payload_row["label"] if payload_row else None,
                "source_row": payload_row["source_row"] if payload_row else None,
            },
            new=None,
            source=deleted_by,
        )


def _backup_db(conn: sqlite3.Connection, target_dir: Path) -> Path | None:
    """Persist a copy of the database for rollback."""

    target_dir.mkdir(parents=True, exist_ok=True)
    tmp = target_dir / f"repair-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.sqlite"
    try:
        with sqlite3.connect(tmp) as dst:
            conn.backup(dst)
        return tmp
    except Exception:
        log.debug("Failed to write repair backup", exc_info=True)
        return None


def _match_deleted_targets(conn: sqlite3.Connection, dataset_id: int, audit_rows: list[sqlite3.Row]) -> list[int]:
    """Return ids of events that should be deleted based on audit entries."""

    if not audit_rows:
        return []
    existing = conn.execute(
        "SELECT id, t_us, label, source_row FROM event WHERE dataset_id = ? AND deleted_utc IS NULL",
        (dataset_id,),
    ).fetchall()
    targets: list[int] = []
    for audit in audit_rows:
        if audit["action"] != "delete":
            continue
        try:
            old_payload = json.loads(audit["old_json"] or "{}")
        except json.JSONDecodeError:
            old_payload = {}
        match_id = old_payload.get("id")
        if match_id:
            targets.append(int(match_id))
            continue
        target_row = old_payload.get("source_row")
        target_ts = old_payload.get("t_us")
        target_label = old_payload.get("label")
        for row in existing:
            if row["id"] in targets:
                continue
            if target_row is not None and row["source_row"] == target_row:
                targets.append(int(row["id"]))
                break
            if target_ts is not None and row["t_us"] is not None and abs(row["t_us"] - target_ts) <= 500:
                if target_label is None or str(row["label"]) == str(target_label):
                    targets.append(int(row["id"]))
                    break
    return targets


def repair_dataset_from_raw(
    conn: sqlite3.Connection,
    dataset_id: int,
    *,
    raw_trace: pd.DataFrame | None = None,
    raw_events: pd.DataFrame | None = None,
    backup_dir: str | Path | None = None,
    source: str = "repair",
) -> dict[str, Any]:
    """
    Rebuild events from raw sources and reapply user edits.

    The current events are soft-deleted (reason='repair_replaced') and the
    rebuilt events are inserted.  Audit entries marked as ``delete`` are
    reapplied to preserve user intent.
    """

    if raw_events is None or raw_events.empty:
        raise ValueError("raw_events must be provided for repair")

    if backup_dir is not None:
        _backup_db(conn, Path(backup_dir))

    audit_rows = conn.execute(
        "SELECT action, event_id, old_json, new_json, source FROM event_audit WHERE dataset_id = ? ORDER BY utc_ts",
        (dataset_id,),
    ).fetchall()

    with conn:
        now = _utc_now()
        conn.execute(
            """
            UPDATE event
               SET deleted_utc = ?, deleted_reason = 'repair_replaced', deleted_by = ?
             WHERE dataset_id = ? AND deleted_utc IS NULL
            """,
            (now, source, dataset_id),
        )

        rebuilt_rows = list(_events.prepare_event_rows(dataset_id, raw_events))
        if rebuilt_rows:
            conn.executemany(
                """
                INSERT INTO event(
                    dataset_id, t_seconds, t_us, label, frame, source_frame, source_row, source_time_str,
                    p_avg, p1, p2, temp, extra_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rebuilt_rows,
            )
        # Reapply deletes from audit
        delete_targets = _match_deleted_targets(conn, dataset_id, audit_rows)
        if delete_targets:
            soft_delete_events(conn, dataset_id, delete_targets, reason="repair_replay", deleted_by=source)

    sigs = _validation.update_dataset_signatures(conn, dataset_id)
    return {
        "dataset_id": dataset_id,
        "inserted": len(raw_events.index),
        "deleted_reapplied": len(delete_targets) if delete_targets else 0,
        "events_signature": sigs["events_signature"],
        "trace_signature": sigs["trace_signature"],
    }
