"""Epoch data model for protocol timeline overlays in Publication Mode.

This module provides a unified epoch representation that can be mapped from
various event sources (setpoints, drug events, bath changes) for rendering
as bars, boxes, and shaded regions above publication traces.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

__all__ = [
    "Epoch",
    "EpochManifest",
    "events_to_epochs",
]


@dataclass
class Epoch:
    """Unified epoch representation for protocol timeline visualization.

    An epoch represents a time span in the experiment with associated metadata
    for rendering (drug application, pressure step, perfusate change, etc.).
    """

    id: str
    channel: str  # "Pressure", "Drug", "Blocker", "Perfusate", "Custom"
    label: str  # Display text (e.g., "U-46619 25 nM", "60 mmHg")
    t_start: float  # seconds from experiment start
    t_end: float  # seconds from experiment start
    style: Literal["bar", "box", "shade"]  # Visual representation
    color: str | None = None  # hex or named; None = theme default
    emphasis: Literal["normal", "strong", "light"] = "normal"  # affects thickness/alpha
    row_index: int = -1  # for manual stacking within channel; -1 = auto
    meta: dict[str, Any] = field(default_factory=dict)  # arbitrary metadata

    def __post_init__(self) -> None:
        """Validate epoch data."""
        if self.t_end < self.t_start:
            raise ValueError(f"Epoch {self.id}: t_end ({self.t_end}) < t_start ({self.t_start})")

        if self.channel not in {"Pressure", "Drug", "Blocker", "Perfusate", "Custom"}:
            # Allow custom channels but warn
            pass

        if self.style not in {"bar", "box", "shade"}:
            raise ValueError(f"Epoch {self.id}: invalid style '{self.style}'")

        if self.emphasis not in {"normal", "strong", "light"}:
            raise ValueError(f"Epoch {self.id}: invalid emphasis '{self.emphasis}'")

    def duration(self) -> float:
        """Return epoch duration in seconds."""
        return self.t_end - self.t_start

    def contains_time(self, t: float) -> bool:
        """Check if time point falls within this epoch."""
        return self.t_start <= t <= self.t_end

    def overlaps(self, other: Epoch) -> bool:
        """Check if this epoch overlaps with another epoch."""
        return not (self.t_end <= other.t_start or other.t_end <= self.t_start)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for JSON export."""
        return {
            "id": self.id,
            "channel": self.channel,
            "label": self.label,
            "t_start": self.t_start,
            "t_end": self.t_end,
            "style": self.style,
            "color": self.color,
            "emphasis": self.emphasis,
            "row_index": self.row_index,
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Epoch:
        """Deserialize from dictionary."""
        return cls(
            id=data["id"],
            channel=data["channel"],
            label=data["label"],
            t_start=data["t_start"],
            t_end=data["t_end"],
            style=data["style"],
            color=data.get("color"),
            emphasis=data.get("emphasis", "normal"),
            row_index=data.get("row_index", -1),
            meta=data.get("meta", {}),
        )


@dataclass
class EpochManifest:
    """Serializable epoch collection for figure export metadata."""

    epochs: list[Epoch]
    epoch_theme: str = "default_v1"
    row_order: list[str] = field(
        default_factory=lambda: ["Pressure", "Drug", "Blocker", "Perfusate", "Custom"]
    )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for JSON/PDF metadata."""
        return {
            "epochs": [epoch.to_dict() for epoch in self.epochs],
            "epoch_theme": self.epoch_theme,
            "row_order": self.row_order,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EpochManifest:
        """Deserialize from dictionary."""
        return cls(
            epochs=[Epoch.from_dict(e) for e in data.get("epochs", [])],
            epoch_theme=data.get("epoch_theme", "default_v1"),
            row_order=data.get("row_order", ["Pressure", "Drug", "Blocker", "Perfusate", "Custom"]),
        )


# --------------------------------------------------------------------------- Event Adapters


def events_to_epochs(
    event_times: list[float],
    event_labels: list[str],
    event_label_meta: list[dict[str, Any]],
    *,
    default_duration: float = 60.0,
    merge_consecutive: bool = True,
) -> list[Epoch]:
    """Convert VasoAnalyzer event lists to Epoch objects.

    Maps event categories to epoch channels:
    - "setpoint" or "pressure" → Pressure channel, style="box"
    - "drug" → Drug channel, style="bar"
    - "blocker" → Blocker channel, style="bar"
    - "bath" or "perfusate" → Perfusate channel, style="shade"
    - Other → Custom channel, style="bar"

    Args:
        event_times: Event timestamps in seconds
        event_labels: Event text labels
        event_label_meta: Event metadata dictionaries (category, priority, etc.)
        default_duration: Default epoch duration when end time is unknown (seconds)
        merge_consecutive: Merge consecutive identical epochs

    Returns:
        List of Epoch objects sorted by start time
    """
    if not event_times or not event_labels or not event_label_meta:
        return []

    def _coerce_float(value: Any) -> float | None:
        """Best-effort conversion to float (ignores invalid values)."""
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    # Build a staging list so we can infer durations per channel
    staged_events: list[dict[str, Any]] = []
    event_iter = zip(event_times, event_labels, event_label_meta, strict=False)
    for idx, (t_raw, label, meta_raw) in enumerate(event_iter):
        meta = dict(meta_raw or {})
        category = meta.get("category", "") or ""
        category = str(category).lower()

        # Determine channel + visual style from metadata category
        if category in {"setpoint", "pressure"}:
            channel = "Pressure"
            style = "box"
            color = "#111111"
            emphasis = "normal"
        elif category == "drug":
            channel = "Drug"
            style = "bar"
            color = "#1f77b4"
            emphasis = "strong"
        elif category == "blocker":
            channel = "Blocker"
            style = "bar"
            color = "#d62728"
            emphasis = "normal"
        elif category in {"bath", "perfusate"}:
            channel = "Perfusate"
            style = "shade"
            color = "#2ca02c"
            emphasis = "light"
        else:
            channel = "Custom"
            style = "bar"
            color = "#7f7f7f"
            emphasis = "normal"

        # Allow explicit color override
        if "color" in meta and meta["color"]:
            color = meta["color"]

        staged_events.append(
            {
                "idx": idx,
                "t": float(t_raw),
                "label": label,
                "meta": meta,
                "channel": channel,
                "style": style,
                "color": color,
                "emphasis": emphasis,
            }
        )

    if not staged_events:
        return []

    # Annotate each staged event with the next timestamp within the same channel
    channel_map: dict[str, list[dict[str, Any]]] = {}
    for payload in staged_events:
        channel_map.setdefault(payload["channel"], []).append(payload)

    for same_channel_events in channel_map.values():
        same_channel_events.sort(key=lambda payload: payload["t"])
        for i, event_payload in enumerate(same_channel_events):
            next_time = (
                same_channel_events[i + 1]["t"] if i + 1 < len(same_channel_events) else None
            )
            event_payload["_next_in_channel"] = next_time

    epochs: list[Epoch] = []
    for payload in staged_events:
        t_start = payload["t"]
        meta = payload["meta"]

        explicit_end = _coerce_float(meta.get("t_end"))
        duration = _coerce_float(meta.get("duration"))

        if explicit_end is not None and explicit_end > t_start:
            t_end = explicit_end
        elif duration is not None and duration > 0:
            t_end = t_start + duration
        else:
            next_time = _coerce_float(payload.get("_next_in_channel"))
            if next_time is not None and next_time > t_start:
                t_end = next_time
            else:
                t_end = t_start + default_duration

        # Guard against zero/negative durations by falling back to default
        if t_end <= t_start:
            t_end = t_start + max(default_duration, 1.0)

        epoch = Epoch(
            id=f"epoch_{payload['idx']}",
            channel=payload["channel"],
            label=payload["label"],
            t_start=t_start,
            t_end=t_end,
            style=payload["style"],
            color=payload["color"],
            emphasis=payload["emphasis"],
            meta=meta.copy(),
        )
        epochs.append(epoch)

    # Sort by start time
    epochs.sort(key=lambda e: e.t_start)

    # Merge consecutive identical epochs if requested
    if merge_consecutive:
        epochs = _merge_consecutive_epochs(epochs)

    return epochs


def _merge_consecutive_epochs(epochs: list[Epoch]) -> list[Epoch]:
    """Merge consecutive epochs with identical channel, label, and style."""
    if len(epochs) <= 1:
        return epochs

    merged: list[Epoch] = []
    current = epochs[0]

    for next_epoch in epochs[1:]:
        # Check if epochs can be merged
        can_merge = (
            current.channel == next_epoch.channel
            and current.label == next_epoch.label
            and current.style == next_epoch.style
            and current.color == next_epoch.color
            and current.emphasis == next_epoch.emphasis
            and abs(current.t_end - next_epoch.t_start) < 1.0  # Within 1 second
        )

        if can_merge:
            # Extend current epoch
            current = Epoch(
                id=current.id,
                channel=current.channel,
                label=current.label,
                t_start=current.t_start,
                t_end=next_epoch.t_end,
                style=current.style,
                color=current.color,
                emphasis=current.emphasis,
                row_index=current.row_index,
                meta=current.meta,
            )
        else:
            # Start new epoch
            merged.append(current)
            current = next_epoch

    # Add the last epoch
    merged.append(current)

    return merged


def pressure_setpoints_to_epochs(
    setpoint_times: list[float],
    setpoint_values: list[float],
    *,
    unit: str = "mmHg",
) -> list[Epoch]:
    """Convert pressure setpoint steps to Pressure epochs.

    Args:
        setpoint_times: Timestamps of pressure changes (seconds)
        setpoint_values: Pressure values at each timestamp
        unit: Pressure unit for labels

    Returns:
        List of Pressure epochs (style="box")
    """
    if not setpoint_times:
        return []

    epochs: list[Epoch] = []

    for i, (t_start, value) in enumerate(zip(setpoint_times, setpoint_values, strict=False)):
        # End time is the start of the next setpoint (or extend to end)
        t_end = setpoint_times[i + 1] if i + 1 < len(setpoint_times) else t_start + 300.0

        epoch = Epoch(
            id=f"pressure_{i}",
            channel="Pressure",
            label=f"{value:.0f} {unit}",
            t_start=t_start,
            t_end=t_end,
            style="box",
            color="#111111",
            emphasis="normal",
            meta={"setpoint_value": value, "unit": unit},
        )
        epochs.append(epoch)

    return epochs


def drug_events_to_epochs(
    drug_start_times: list[float],
    drug_end_times: list[float],
    drug_names: list[str],
    drug_concentrations: list[float],
    *,
    concentration_unit: str = "nM",
    channel: str = "Drug",
) -> list[Epoch]:
    """Convert drug application events to Drug/Blocker epochs.

    Args:
        drug_start_times: Drug application start times (seconds)
        drug_end_times: Drug washout/end times (seconds)
        drug_names: Drug names
        drug_concentrations: Drug concentrations
        concentration_unit: Concentration unit for labels
        channel: "Drug" or "Blocker"

    Returns:
        List of Drug/Blocker epochs (style="bar")
    """
    epochs: list[Epoch] = []

    color = "#1f77b4" if channel == "Drug" else "#d62728"
    emphasis: Literal["normal", "strong", "light"] = "strong" if channel == "Drug" else "normal"

    for i, (t_start, t_end, name, conc) in enumerate(
        zip(drug_start_times, drug_end_times, drug_names, drug_concentrations, strict=False)
    ):
        epoch = Epoch(
            id=f"{channel.lower()}_{i}",
            channel=channel,
            label=f"{name} {conc:.1f} {concentration_unit}",
            t_start=t_start,
            t_end=t_end,
            style="bar",
            color=color,
            emphasis=emphasis,
            meta={"drug_name": name, "concentration": conc, "unit": concentration_unit},
        )
        epochs.append(epoch)

    return epochs


def bath_events_to_epochs(
    bath_start_times: list[float],
    bath_end_times: list[float],
    bath_labels: list[str],
) -> list[Epoch]:
    """Convert bath/perfusate switch events to Perfusate epochs.

    Args:
        bath_start_times: Bath switch start times (seconds)
        bath_end_times: Bath switch end times (seconds)
        bath_labels: Bath composition labels

    Returns:
        List of Perfusate epochs (style="shade")
    """
    epochs: list[Epoch] = []

    for i, (t_start, t_end, label) in enumerate(
        zip(bath_start_times, bath_end_times, bath_labels, strict=False)
    ):
        epoch = Epoch(
            id=f"perfusate_{i}",
            channel="Perfusate",
            label=label,
            t_start=t_start,
            t_end=t_end,
            style="shade",
            color="#2ca02c",
            emphasis="light",
            meta={"bath_label": label},
        )
        epochs.append(epoch)

    return epochs
