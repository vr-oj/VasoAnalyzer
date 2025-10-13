from __future__ import annotations

"""Service interfaces and typing helpers."""

from pathlib import Path
from typing import Protocol, Sequence, runtime_checkable, Mapping, Any, Optional

__all__ = [
    "TraceProvider",
    "EventProvider",
    "AssetProvider",
    "ProjectRepository",
]


@runtime_checkable
class TraceProvider(Protocol):
    """Capability to provide trace samples for a dataset."""

    def get_trace(
        self,
        dataset_id: int,
        t0: Optional[float] = None,
        t1: Optional[float] = None,
    ) -> "Any":
        ...


@runtime_checkable
class EventProvider(Protocol):
    """Capability to provide event rows for a dataset."""

    def get_events(
        self,
        dataset_id: int,
        t0: Optional[float] = None,
        t1: Optional[float] = None,
    ) -> "Any":
        ...


@runtime_checkable
class AssetProvider(Protocol):
    """Capability to list and retrieve project assets."""

    def list_assets(self, dataset_id: int) -> Sequence[Mapping[str, Any]]:
        ...

    def get_asset_bytes(self, asset_id: int) -> bytes:
        ...

    def add_or_update_asset(
        self,
        dataset_id: int,
        role: str,
        payload: Any,
        *,
        embed: bool,
        mime: Optional[str] = None,
        chunk_size: int = 8 * 1024 * 1024,
    ) -> int:
        ...


@runtime_checkable
class ProjectRepository(TraceProvider, EventProvider, AssetProvider, Protocol):
    """Unified repository abstraction for project storage."""

    path: Optional[Path]

    def mark_dirty(self) -> None: ...

    def commit(self) -> None: ...

    def close(self) -> None: ...

    def write_meta(self, values: Mapping[str, Any]) -> None: ...

    def add_dataset(
        self,
        name: str,
        trace_data: Any,
        events_data: Optional[Any],
        *,
        metadata: Optional[Mapping[str, Any]] = None,
        tiff_path: Optional[str] = None,
        embed_tiff: bool = False,
        chunk_size: int = 8 * 1024 * 1024,
        thumbnail_png: Optional[bytes] = None,
    ) -> int:
        ...

    def update_dataset_meta(self, dataset_id: int, **fields: Any) -> None: ...

    def add_events(self, rows: Sequence[Mapping[str, Any]]) -> int:
        ...

    def update_event(self, event_id: int, values: Mapping[str, Any]) -> None:
        ...

    def delete_events(self, ids: Sequence[int]) -> int:
        ...

    def write_trace(self, trace_id: Any, data: Any) -> None:
        ...

    def add_result(self, dataset_id: int, kind: str, version: str, payload: Mapping[str, Any]) -> int:
        ...

    def get_results(self, dataset_id: int, kind: Optional[str] = None) -> Sequence[Mapping[str, Any]]:
        ...

    def iter_datasets(self) -> Sequence[Mapping[str, Any]]:
        ...

    def save(self) -> None:
        ...
