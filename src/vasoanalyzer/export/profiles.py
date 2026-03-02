"""Canonical export profile definitions for Excel-ready outputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

OutputShape = Literal["table", "single_column"]


@dataclass(frozen=True)
class ColumnDef:
    key: str
    header: str
    optional: bool = False


@dataclass(frozen=True)
class ExportProfile:
    profile_id: str
    display_name: str
    output_shape: OutputShape
    column_defs: tuple[ColumnDef, ...] | None
    requires_event_labels: tuple[str, ...]
    single_column_header: str | None = None


EVENT_TABLE_ROW_PER_EVENT_ID = "event_table_row_per_event"
EVENT_VALUES_SINGLE_COLUMN_ID = "event_values_single_column"
PRESSURE_CURVE_STANDARD_ID = "pressure_curve_standard"

PRESSURE_CURVE_STANDARD_LABELS = (
    "20 mmHg – Max",
    "40 mmHg – Max",
    "60 mmHg – Max",
    "60 mmHg – Tone",
    "80 mmHg – Max",
    "80 mmHg – Tone",
    "100 mmHg – Max",
    "100 mmHg – Tone",
    "120 mmHg – Max",
    "120 mmHg – Tone",
)

EVENT_TABLE_ROW_PER_EVENT = ExportProfile(
    profile_id=EVENT_TABLE_ROW_PER_EVENT_ID,
    display_name="Event Table – Row-per-Event",
    output_shape="table",
    column_defs=(
        ColumnDef("time_s", "Time (s)"),
        ColumnDef("event_label", "Event Label"),
        ColumnDef("value", "Value"),
        ColumnDef("source", "Source", optional=True),
    ),
    requires_event_labels=(),
)

EVENT_VALUES_SINGLE_COLUMN = ExportProfile(
    profile_id=EVENT_VALUES_SINGLE_COLUMN_ID,
    display_name="Event Values – Single Column (Excel Paste)",
    output_shape="single_column",
    column_defs=None,
    requires_event_labels=(),
    single_column_header="Value",
)

PRESSURE_CURVE_STANDARD = ExportProfile(
    profile_id=PRESSURE_CURVE_STANDARD_ID,
    display_name="Pressure Curve – Standard",
    output_shape="table",
    column_defs=(
        ColumnDef("event_label", "Event Label"),
        ColumnDef("value", "Value"),
    ),
    requires_event_labels=PRESSURE_CURVE_STANDARD_LABELS,
)

EXPORT_PROFILES = (
    EVENT_TABLE_ROW_PER_EVENT,
    EVENT_VALUES_SINGLE_COLUMN,
    PRESSURE_CURVE_STANDARD,
)

EXPORT_PROFILE_BY_ID = {profile.profile_id: profile for profile in EXPORT_PROFILES}


def get_profile(profile_id: str) -> ExportProfile:
    try:
        return EXPORT_PROFILE_BY_ID[profile_id]
    except KeyError as exc:
        raise KeyError(f"Unknown export profile: {profile_id}") from exc
