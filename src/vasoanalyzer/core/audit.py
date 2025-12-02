"""Audit log helpers for manual trace editing."""

from __future__ import annotations

import getpass
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

__all__ = [
    "EditAction",
    "compress_indices",
    "expand_ranges",
    "serialize_edit_log",
    "deserialize_edit_log",
]


def _default_user() -> str:
    try:
        return getpass.getuser() or "unknown"
    except Exception:
        return "unknown"


def _ensure_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def compress_indices(indices: Sequence[int]) -> list[tuple[int, int]]:
    """Return inclusive ranges covering the provided indices."""

    if not indices:
        return []

    sorted_idx = sorted(int(i) for i in dict.fromkeys(indices))
    ranges: list[tuple[int, int]] = []
    start = prev = sorted_idx[0]
    for idx in sorted_idx[1:]:
        if idx == prev + 1:
            prev = idx
            continue
        ranges.append((start, prev))
        start = prev = idx
    ranges.append((start, prev))
    return ranges


def expand_ranges(ranges: Iterable[Sequence[int]]) -> tuple[int, ...]:
    """Expand ``(start, end)`` inclusive ranges back into explicit indices."""

    values: list[int] = []
    for entry in ranges:
        if not entry:
            continue
        if len(entry) == 1:
            start = end = int(entry[0])
        else:
            start, end = int(entry[0]), int(entry[1])
        if end < start:
            start, end = end, start
        values.extend(range(start, end + 1))
    return tuple(values)


def _normalize_channel(channel: str) -> str:
    lc = channel.strip().lower()
    if lc in {"inner", "id", "diam_inner", "inner_diameter"}:
        return "inner"
    if lc in {"outer", "od", "diam_outer", "outer_diameter"}:
        return "outer"
    raise ValueError(f"Unsupported channel: {channel}")


def _channel_label(channel: str) -> str:
    return "ID" if channel == "inner" else "OD"


@dataclass(frozen=True)
class EditAction:
    """Represent a single mutation to the cleaned trace."""

    channel: str
    op: str
    indices: tuple[int, ...]
    t_bounds: tuple[float, float]
    params: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(
        default_factory=lambda: datetime.utcnow().replace(tzinfo=timezone.utc)
    )
    user: str = field(default_factory=_default_user)

    def __post_init__(self) -> None:
        object.__setattr__(self, "channel", _normalize_channel(self.channel))
        object.__setattr__(self, "op", str(self.op))
        if not isinstance(self.indices, tuple):
            object.__setattr__(self, "indices", tuple(int(i) for i in self.indices))
        if not isinstance(self.t_bounds, tuple):
            object.__setattr__(
                self,
                "t_bounds",
                tuple(float(v) for v in self.t_bounds),
            )

    @property
    def count(self) -> int:
        return len(self.indices)

    @property
    def first_index(self) -> int:
        return min(self.indices) if self.indices else -1

    @property
    def last_index(self) -> int:
        return max(self.indices) if self.indices else -1

    def summary(self) -> str:
        """Return a concise, user-facing description of the edit."""

        channel_label = _channel_label(self.channel)
        op_labels = {
            "delete_points": "Delete",
            "restore_points": "Restore",
            "connect_across": "Connect",
        }
        op_label = op_labels.get(self.op, self.op)

        t0, t1 = self.t_bounds
        ts = _ensure_utc(self.timestamp)
        ts_str = ts.strftime("%Y-%m-%d %H:%M:%SZ")

        parts = [
            ts_str,
            f"{channel_label} {op_label}",
            f"{self.count} pts",
            f"{t0:.3f}–{t1:.3f} s",
        ]

        method = self.params.get("method")
        if method:
            parts.append(f"method={method}")
        fallback = self.params.get("fallback")
        if fallback:
            parts.append(f"fallback={fallback}")

        return " — ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "channel": _channel_label(self.channel),
            "op": self.op,
            "indices": compress_indices(self.indices),
            "t_bounds": [float(v) for v in self.t_bounds],
            "params": dict(self.params or {}),
            "timestamp": _ensure_utc(self.timestamp).isoformat().replace("+00:00", "Z"),
            "user": self.user,
        }
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> EditAction:
        channel = payload.get("channel", "ID")
        indices = expand_ranges(payload.get("indices", ()))
        t_bounds_raw = payload.get("t_bounds")
        if isinstance(t_bounds_raw, list | tuple) and len(t_bounds_raw) >= 2:
            t_bounds: tuple[float, float] = (float(t_bounds_raw[0]), float(t_bounds_raw[1]))
        else:
            t_bounds = (0.0, 0.0)
        params = payload.get("params") or {}
        timestamp_raw = payload.get("timestamp")
        if timestamp_raw:
            try:
                ts = datetime.fromisoformat(str(timestamp_raw).replace("Z", "+00:00"))
            except Exception:
                ts = datetime.utcnow().replace(tzinfo=timezone.utc)
        else:
            ts = datetime.utcnow().replace(tzinfo=timezone.utc)
        user = payload.get("user") or _default_user()
        return cls(
            channel=channel,
            op=str(payload.get("op", "")),
            indices=indices,
            t_bounds=t_bounds,
            params=dict(params),
            timestamp=_ensure_utc(ts),
            user=user,
        )


def serialize_edit_log(actions: Sequence[EditAction]) -> list[dict[str, Any]]:
    return [action.to_dict() for action in actions]


def deserialize_edit_log(payload: Iterable[dict[str, Any]]) -> tuple[EditAction, ...]:
    actions: list[EditAction] = []
    for entry in payload:
        try:
            actions.append(EditAction.from_dict(entry))
        except Exception:
            continue
    return tuple(actions)
