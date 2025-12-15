"""Service interfaces and typing helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol, TypedDict, runtime_checkable

__all__ = [
    "TraceProvider",
    "EventProvider",
    "AssetProvider",
    "ProjectRepository",
    "AssetRecord",
    "ResultRecord",
    "DatasetRecord",
]


class AssetRecord(TypedDict, total=False):
    id: int
    role: str
    note: str | None
    kind: str
    sha256: str
    size_bytes: int
    compressed: bool
    chunk_size: int
    original_name: str | None
    mime: str | None


class ResultRecord(TypedDict, total=False):
    id: int
    kind: str
    version: str
    created_utc: str
    payload: Mapping[str, Any]


class DatasetRecord(TypedDict, total=False):
    id: int
    name: str
    created_utc: str
    notes: str | None
    fps: float | None
    pixel_size_um: float | None
    t0_seconds: float | None
    extra: Mapping[str, Any]


@runtime_checkable
class TraceProvider(Protocol):
    """Capability to provide trace samples for a dataset."""

    def get_trace(
        self,
        dataset_id: int,
        t0: float | None = None,
        t1: float | None = None,
    ) -> Any: ...


@runtime_checkable
class EventProvider(Protocol):
    """Capability to provide event rows for a dataset."""

    def get_events(
        self,
        dataset_id: int,
        t0: float | None = None,
        t1: float | None = None,
    ) -> Any: ...


@runtime_checkable
class AssetProvider(Protocol):
    """Capability to list and retrieve project assets."""

    def list_assets(self, dataset_id: int) -> Sequence[AssetRecord]: ...

    def get_asset_bytes(self, asset_id: int) -> bytes: ...

    def add_or_update_asset(
        self,
        dataset_id: int,
        role: str,
        payload: Any,
        *,
        embed: bool,
        mime: str | None = None,
        chunk_size: int = 2 * 1024 * 1024,
        note: str | None = None,
        original_name: str | None = None,
    ) -> int: ...


@runtime_checkable
class ProjectRepository(TraceProvider, EventProvider, AssetProvider, Protocol):
    """Unified repository abstraction for project storage."""

    path: Path | None

    def mark_dirty(self) -> None: ...

    def commit(self) -> None: ...

    def close(self) -> None: ...

    def write_meta(self, values: Mapping[str, Any]) -> None: ...

    def add_dataset(
        self,
        name: str,
        trace_data: Any,
        events_data: Any | None,
        *,
        metadata: Mapping[str, Any] | None = None,
        tiff_path: str | None = None,
        embed_tiff: bool = False,
        chunk_size: int = 2 * 1024 * 1024,
        thumbnail_png: bytes | None = None,
    ) -> int: ...

    def update_dataset_meta(self, dataset_id: int, **fields: Any) -> None: ...

    def add_events(self, rows: Sequence[Mapping[str, Any]]) -> int: ...

    def update_event(self, event_id: int, values: Mapping[str, Any]) -> None: ...

    def delete_events(self, ids: Sequence[int]) -> int: ...

    def write_trace(self, trace_id: Any, data: Any) -> None: ...

    def add_result(
        self, dataset_id: int, kind: str, version: str, payload: Mapping[str, Any]
    ) -> int: ...

    def get_results(self, dataset_id: int, kind: str | None = None) -> Sequence[ResultRecord]: ...

    def iter_datasets(self) -> Sequence[DatasetRecord]: ...

    def save(self) -> None: ...

    # Figure recipes
    def add_figure_recipe(
        self,
        dataset_id: int,
        name: str,
        spec_json: str,
        *,
        source: str = "current_view",
        trace_key: str | None = None,
        x_min: float | None = None,
        x_max: float | None = None,
        y_min: float | None = None,
        y_max: float | None = None,
        export_background: str = "white",
        recipe_id: str | None = None,
    ) -> str: ...

    def update_figure_recipe(
        self,
        recipe_id: str,
        *,
        name: str | None = None,
        spec_json: str | None = None,
        source: str | None = None,
        trace_key: str | None = None,
        x_min: float | None = None,
        x_max: float | None = None,
        y_min: float | None = None,
        y_max: float | None = None,
        export_background: str | None = None,
    ) -> None: ...

    def list_figure_recipes(self, dataset_id: int) -> Sequence[Mapping[str, Any]]: ...

    def get_figure_recipe(self, recipe_id: str) -> Mapping[str, Any] | None: ...

    def delete_figure_recipe(self, recipe_id: str) -> None: ...

    def rename_figure_recipe(self, recipe_id: str, name: str) -> None: ...
