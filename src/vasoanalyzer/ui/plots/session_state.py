"""Helpers for binding datasets to plot hosts without a full MainWindow."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from vasoanalyzer.core import project as project_module
from vasoanalyzer.core.project import Project, SampleN
from vasoanalyzer.core.trace_model import TraceModel
from vasoanalyzer.storage import sqlite_store
from vasoanalyzer.ui.plots.channel_track import ChannelTrackSpec

log = logging.getLogger(__name__)


def bind_project_dataset_to_plot_host(project: Project, dataset_id: int, plot_host: Any) -> SampleN:
    """Materialize trace/events for ``dataset_id`` and bind to ``plot_host``."""

    sample = _find_sample_by_dataset_id(project, dataset_id)
    if sample is None:
        raise ValueError(f"Dataset {dataset_id} not found in project")

    _ensure_sample_data_loaded(project, sample)
    if sample.trace_data is None:
        raise ValueError("trace_data is not available for plot binding")

    model = TraceModel.from_dataframe(sample.trace_data)
    specs = _channel_specs_for_model(model)
    if hasattr(plot_host, "ensure_channels"):
        plot_host.ensure_channels(specs)

    if hasattr(plot_host, "set_model"):
        plot_host.set_model(model)
    else:
        plot_host.set_trace_model(model)

    if isinstance(sample.events_data, pd.DataFrame) and not sample.events_data.empty:
        times, labels = _extract_event_payload(sample.events_data)
        plot_host.set_events(times, labels=labels)

    return sample


def apply_session_state_to_plot_host(plot_host: Any, state: dict | None) -> None:
    """Apply minimal session state to ``plot_host`` (time window + visibility)."""

    if not state:
        return

    xlim = state.get("axis_xlim")
    if isinstance(xlim, (tuple, list)) and len(xlim) == 2:
        try:
            plot_host.set_time_window(float(xlim[0]), float(xlim[1]))
        except Exception:
            log.debug("Failed to apply time window to plot host", exc_info=True)

    for key, track_id in (
        ("inner_trace_visible", "inner"),
        ("outer_trace_visible", "outer"),
        ("avg_pressure_visible", "avg_pressure"),
        ("set_pressure_visible", "set_pressure"),
    ):
        if key in state:
            _set_channel_visibility(plot_host, track_id, bool(state[key]))

    event_lines_visible = state.get("event_lines_visible")
    if event_lines_visible is not None and hasattr(plot_host, "set_event_lines_visible"):
        plot_host.set_event_lines_visible(bool(event_lines_visible))

    event_label_mode = state.get("event_label_mode")
    if event_label_mode and hasattr(plot_host, "set_event_label_mode"):
        plot_host.set_event_label_mode(str(event_label_mode))


def _find_sample_by_dataset_id(project: Project, dataset_id: int) -> SampleN | None:
    for experiment in project.experiments:
        for sample in experiment.samples:
            if sample.dataset_id == dataset_id:
                return sample
    return None


def _ensure_sample_data_loaded(project: Project, sample: SampleN) -> None:
    if sample.trace_data is not None and sample.events_data is not None:
        return

    if not project.path:
        raise ValueError("Project path required to load dataset")

    store = sqlite_store.open_project(project.path)
    try:
        if sample.trace_data is None and sample.dataset_id is not None:
            trace_df = sqlite_store.get_trace(store, sample.dataset_id)
            formatted = project_module._format_trace_df(
                trace_df,
                getattr(sample, "trace_column_labels", None),
                getattr(sample, "name", None),
            )
            sample.trace_data = formatted
        if sample.events_data is None and sample.dataset_id is not None:
            events_df = sqlite_store.get_events(store, sample.dataset_id)
            sample.events_data = project_module._format_events_df(events_df)
    finally:
        store.close()


def _channel_specs_for_model(model: TraceModel) -> list[ChannelTrackSpec]:
    specs: list[ChannelTrackSpec] = [
        ChannelTrackSpec(track_id="inner", component="inner", label="Inner Diameter (um)")
    ]
    if model.outer_full is not None:
        specs.append(
            ChannelTrackSpec(
                track_id="outer",
                component="outer",
                label="Outer Diameter (um)",
            )
        )
    if model.avg_pressure_full is not None:
        specs.append(
            ChannelTrackSpec(
                track_id="avg_pressure",
                component="avg_pressure",
                label="Avg Pressure (mmHg)",
            )
        )
    if model.set_pressure_full is not None:
        specs.append(
            ChannelTrackSpec(
                track_id="set_pressure",
                component="set_pressure",
                label="Set Pressure (mmHg)",
            )
        )
    return specs


def _extract_event_payload(
    events_df: pd.DataFrame,
) -> tuple[list[float], list[str]]:
    if events_df is None or events_df.empty:
        return ([], [])

    col_map = {str(col).strip().lower(): col for col in events_df.columns}
    time_col = None
    for key in ("t_seconds", "time (s)", "time", "timestamp"):
        if key in col_map:
            time_col = col_map[key]
            break
    label_col = None
    for key in ("label", "event", "event label", "event_label", "label (event)"):
        if key in col_map:
            label_col = col_map[key]
            break

    if time_col is None:
        return ([], [])

    times = pd.to_numeric(events_df[time_col], errors="coerce")
    if label_col is None:
        labels = pd.Series([""] * len(events_df), index=events_df.index)
    else:
        labels = events_df[label_col].astype(str)

    mask = times.notna()
    return (
        times[mask].astype(float).tolist(),
        labels[mask].astype(str).tolist(),
    )


def _set_channel_visibility(plot_host: Any, track_id: str, visible: bool) -> None:
    if hasattr(plot_host, "set_channel_visible"):
        plot_host.set_channel_visible(track_id, visible)
        return
    if hasattr(plot_host, "set_channel_visibility"):
        plot_host.set_channel_visibility(track_id, visible)
