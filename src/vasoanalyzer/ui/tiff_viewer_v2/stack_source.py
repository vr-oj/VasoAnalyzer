# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Stack data sources for the TIFF viewer v2."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class StackSource(Protocol):
    """Interface for retrieving frames from a stack."""

    def __len__(self) -> int: ...

    def get_frame(self, page_index: int): ...

    @property
    def source_kind(self) -> str: ...


class InMemoryStackSource:
    """Adapter for in-memory frame stacks."""

    def __init__(self, frames: Sequence[Any], *, source_kind: str = "in-memory") -> None:
        self._frames = list(frames) if frames is not None else []
        self._source_kind = source_kind

    def __len__(self) -> int:
        return len(self._frames)

    def get_frame(self, page_index: int):
        if not self._frames:
            return None
        try:
            idx = int(page_index)
        except (TypeError, ValueError):
            return None
        if idx < 0 or idx >= len(self._frames):
            return None
        return self._frames[idx]

    @property
    def source_kind(self) -> str:
        return self._source_kind


__all__ = ["InMemoryStackSource", "StackSource"]
