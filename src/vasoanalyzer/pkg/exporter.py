from __future__ import annotations

import io
import mimetypes
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

from vasoanalyzer.pkg.blobs import compute_sha256
from vasoanalyzer.pkg.models import (
    ChannelSpec,
    DatasetMeta,
    Event,
    ProjectMeta,
    RefEntry,
    Sampling,
)
from vasoanalyzer.pkg.package import VasoPackage


def export_project_to_package(
    project: Project,
    dest: Path,
    *,
    base_dir: Path,
    timezone: str | None = None,
) -> VasoPackage:
    package = VasoPackage.create(dest, title=project.name or dest.stem)
    package.project = ProjectMeta(
        title=project.name or dest.stem,
        timezone=timezone,
        tags=list(project.tags or []),
    )

    all_events: list[Event] = []

    for exp_index, experiment in enumerate(project.experiments):
        for sample_index, sample in enumerate(experiment.samples):
            dataset_meta = _build_dataset_meta(sample, exp_index, sample_index)
            parquet_bytes, csv_bytes = _serialise_trace(sample)
            refs = list(_build_refs(sample, base_dir))
            package.add_dataset(
                dataset_meta, refs=refs, channels_parquet=parquet_bytes, channels_csv=csv_bytes
            )
            all_events.extend(_convert_events(dataset_meta.id, sample))

    if all_events:
        package.set_events(all_events)
    else:
        package.set_events([])

    package.save_project_meta()
    return package


def _build_dataset_meta(sample: SampleN, exp_index: int, sample_index: int) -> DatasetMeta:
    trace_df = getattr(sample, "trace_data", None)
    sampling = Sampling(rate_hz=_infer_sampling_rate(trace_df))
    channels = _build_channels(trace_df)
    modality = sample.column or "trace"
    name = sample.name or f"Sample {exp_index + 1}-{sample_index + 1}"
    return DatasetMeta(
        name=name,
        modality=modality,
        sampling=sampling,
        channels=channels or [ChannelSpec(key="value", unit="unitless")],
    )


def _serialise_trace(sample: SampleN) -> tuple[bytes | None, bytes | None]:
    trace_df = getattr(sample, "trace_data", None)
    if trace_df is None or not isinstance(trace_df, pd.DataFrame) or trace_df.empty:
        return None, None

    csv_buffer = io.StringIO()
    trace_df.to_csv(csv_buffer, index=False)
    csv_bytes = csv_buffer.getvalue().encode("utf-8")

    parquet_bytes: bytes | None = None
    try:
        parquet_buffer = io.BytesIO()
        trace_df.to_parquet(parquet_buffer, index=False)
        parquet_bytes = parquet_buffer.getvalue()
    except (ImportError, ValueError):
        parquet_bytes = None

    return parquet_bytes, csv_bytes


def _build_refs(sample: SampleN, base_dir: Path) -> Iterable[RefEntry]:
    if getattr(sample, "trace_path", None):
        resolved = _resolve_path(sample.trace_path, base_dir)
        if resolved and resolved.exists():
            yield _make_ref_entry(resolved, role="trace")
    if getattr(sample, "events_path", None):
        resolved = _resolve_path(sample.events_path, base_dir)
        if resolved and resolved.exists():
            yield _make_ref_entry(resolved, role="events")


def _convert_events(dataset_id: str, sample: SampleN) -> list[Event]:
    events_df = getattr(sample, "events_data", None)
    if events_df is None or not isinstance(events_df, pd.DataFrame) or events_df.empty:
        return []

    lower_map = {col.lower(): col for col in events_df.columns}
    time_col = next((lower_map[key] for key in lower_map if key.startswith("time")), None)
    label_col = next((lower_map[key] for key in lower_map if key.startswith("label")), None)
    lane_col = lower_map.get("lane")

    if time_col is None or label_col is None:
        return []

    events: list[Event] = []
    for index, row in events_df.iterrows():
        event_id = str(row.get("id", f"ev-{index:04d}"))
        try:
            t_value = float(row[time_col])
        except Exception:
            continue
        label = str(row[label_col])
        lane = str(row[lane_col]) if lane_col and lane_col in row else None
        events.append(Event(id=event_id, dataset_id=dataset_id, t=t_value, label=label, lane=lane))
    return events


def _build_channels(trace_df: pd.DataFrame | None) -> list[ChannelSpec]:
    if trace_df is None or trace_df.empty:
        return []
    channels: list[ChannelSpec] = []
    for column in trace_df.columns:
        channels.append(ChannelSpec(key=str(column), unit="unitless"))
    return channels


def _infer_sampling_rate(trace_df: pd.DataFrame | None) -> float:
    if trace_df is None or trace_df.empty:
        return 1.0
    for column in trace_df.columns:
        if str(column).lower().startswith("time"):
            try:
                series = trace_df[column].astype(float)
                diffs = series.diff().dropna()
                if not diffs.empty:
                    mean = float(diffs.mean())
                    if mean > 0:
                        return max(1.0, 1.0 / mean)
            except Exception:
                continue
    return 1.0


def _resolve_path(path_str: str, base_dir: Path) -> Path | None:
    candidate = Path(path_str)
    if not candidate.is_absolute():
        candidate = (base_dir / candidate).resolve()
    return candidate if candidate.exists() else None


def _make_ref_entry(path: Path, role: str) -> RefEntry:
    size = path.stat().st_size
    mime, _ = mimetypes.guess_type(path.name)
    digest = compute_sha256(path)
    return RefEntry(
        sha256=digest,
        size=size,
        mime=mime or "application/octet-stream",
        role=role,
        uri=path.as_posix(),
    )


if TYPE_CHECKING:  # pragma: no cover - typing only
    from vasoanalyzer.core.project import Project, SampleN
