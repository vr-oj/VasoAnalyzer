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


@runtime_checkable
class ProjectRepository(TraceProvider, EventProvider, AssetProvider, Protocol):
    """Unified repository abstraction for project storage."""

    path: Optional[Path]

    def mark_dirty(self) -> None: ...

    def commit(self) -> None: ...

    def close(self) -> None: ...
