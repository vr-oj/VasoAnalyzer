from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from vasoanalyzer.services.types import ProjectRepository

__all__ = ["ProjectContext"]


@dataclass
class ProjectContext:
    """Container for an opened project repository and metadata."""

    path: str
    repo: ProjectRepository
    meta: dict[str, Any]

    def close(self) -> None:
        self.repo.close()
