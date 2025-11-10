from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from vasoanalyzer.services.types import ProjectRepository

if TYPE_CHECKING:
    from vasoanalyzer.core.file_lock import ProjectFileLock

__all__ = ["ProjectContext"]

log = logging.getLogger(__name__)


@dataclass
class ProjectContext:
    """Container for an opened project repository and metadata."""

    path: str
    repo: ProjectRepository
    meta: dict[str, Any]
    file_lock: ProjectFileLock | None = field(default=None, repr=False)

    def close(self) -> None:
        """Close the repository and release file lock."""
        try:
            self.repo.close()
        except Exception as e:
            log.error(f"Error closing repository: {e}", exc_info=True)
        finally:
            # Always release lock even if repo.close() fails
            if self.file_lock is not None:
                try:
                    self.file_lock.release()
                except Exception as e:
                    log.error(f"Error releasing file lock: {e}", exc_info=True)
