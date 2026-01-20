"""Build export tables from event rows and profiles."""

from __future__ import annotations

from dataclasses import dataclass
import math
from collections.abc import Sequence

from .profiles import (
    ExportProfile,
    EVENT_TABLE_ROW_PER_EVENT_ID,
    EVENT_VALUES_SINGLE_COLUMN_ID,
    PRESSURE_CURVE_STANDARD_ID,
)


@dataclass(frozen=True)
class EventRecord:
    label: str
    time_s: float | None
    value: float | None
    source: str | None
    order: int


@dataclass(frozen=True)
class ExportTable:
    headers: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...]
    warnings: tuple[str, ...] = ()


def _coerce_float(value: object | None) -> float | None:
    if value is None:
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(num) or math.isinf(num):
        return None
    return num


def events_from_rows(
    rows: Sequence[Sequence[object]], *, source: str | None = None
) -> list[EventRecord]:
    events: list[EventRecord] = []
    for order, row in enumerate(rows):
        label = ""
        time_s = None
        value = None
        if len(row) > 0 and row[0] is not None:
            label = str(row[0])
        if len(row) > 1:
            time_s = _coerce_float(row[1])
        if len(row) > 2:
            value = _coerce_float(row[2])
        events.append(
            EventRecord(
                label=label,
                time_s=time_s,
                value=value,
                source=source,
                order=order,
            )
        )
    return events


def build_export_table(
    profile: ExportProfile,
    events: Sequence[EventRecord],
    *,
    order_labels: Sequence[str] | None = None,
    preserve_event_order: bool = True,
) -> ExportTable:
    if profile.profile_id == EVENT_TABLE_ROW_PER_EVENT_ID:
        return _build_row_per_event(profile, events)
    if profile.profile_id == EVENT_VALUES_SINGLE_COLUMN_ID:
        return _build_single_column(
            profile,
            events,
            order_labels=order_labels,
            preserve_event_order=preserve_event_order,
        )
    if profile.profile_id == PRESSURE_CURVE_STANDARD_ID:
        return _build_pressure_curve(profile, events)
    raise ValueError(f"Unsupported export profile: {profile.profile_id}")


def _time_sort_key(event: EventRecord) -> tuple[int, float, int]:
    if event.time_s is None:
        return (1, 0.0, event.order)
    return (0, event.time_s, event.order)


def _value_for_key(event: EventRecord, key: str) -> object | None:
    if key == "time_s":
        return event.time_s
    if key == "event_label":
        return event.label
    if key == "value":
        return event.value
    if key == "source":
        return event.source
    return None


def _headers_for_profile(profile: ExportProfile, *, include_optional: bool) -> tuple[str, ...]:
    headers: list[str] = []
    for col in profile.column_defs or ():
        if col.optional and not include_optional:
            continue
        headers.append(col.header)
    return tuple(headers)


def _build_row_per_event(profile: ExportProfile, events: Sequence[EventRecord]) -> ExportTable:
    sorted_events = sorted(events, key=_time_sort_key)
    include_source = any(event.source for event in sorted_events)
    headers = _headers_for_profile(profile, include_optional=include_source)
    rows: list[tuple[object, ...]] = []
    for event in sorted_events:
        row: list[object] = []
        for col in profile.column_defs or ():
            if col.optional and not include_source:
                continue
            row.append(_value_for_key(event, col.key))
        rows.append(tuple(row))
    return ExportTable(headers=headers, rows=tuple(rows))


def _build_single_column(
    profile: ExportProfile,
    events: Sequence[EventRecord],
    *,
    order_labels: Sequence[str] | None,
    preserve_event_order: bool,
) -> ExportTable:
    ordered_events = _ordered_events(
        events, order_labels=order_labels, preserve_event_order=preserve_event_order
    )
    header = profile.single_column_header or "Value"
    rows = tuple((event.value,) for event in ordered_events)
    return ExportTable(headers=(header,), rows=rows)


def _ordered_events(
    events: Sequence[EventRecord],
    *,
    order_labels: Sequence[str] | None,
    preserve_event_order: bool,
) -> list[EventRecord]:
    if order_labels:
        ordered: list[EventRecord] = []
        used: set[int] = set()
        for label in order_labels:
            for event in events:
                if event.label == label and event.order not in used:
                    ordered.append(event)
                    used.add(event.order)
                    break
        return ordered
    if preserve_event_order:
        return sorted(events, key=lambda event: event.order)
    return list(events)


def _build_pressure_curve(profile: ExportProfile, events: Sequence[EventRecord]) -> ExportTable:
    label_order = profile.requires_event_labels or ()
    headers = _headers_for_profile(profile, include_optional=False)
    events_by_label: dict[str, list[EventRecord]] = {}
    for event in events:
        events_by_label.setdefault(event.label, []).append(event)

    rows: list[tuple[object, ...]] = []
    missing: list[str] = []
    for label in label_order:
        matches = events_by_label.get(label)
        if matches:
            rows.append((label, matches[0].value))
        else:
            missing.append(label)

    warnings: tuple[str, ...] = ()
    if missing:
        warnings = (f"Missing expected event labels: {', '.join(missing)}",)

    return ExportTable(headers=headers, rows=tuple(rows), warnings=warnings)
