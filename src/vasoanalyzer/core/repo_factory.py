from __future__ import annotations

from vasoanalyzer.services.types import ProjectRepository

__all__ = ["get_repo"]


def get_repo(path: str) -> ProjectRepository:
    """Return a ProjectRepository for ``path``. Currently uses SQLite."""

    from vasoanalyzer.services.project_service import open_project_repository

    return open_project_repository(path)
