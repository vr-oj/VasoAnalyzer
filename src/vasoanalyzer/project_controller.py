from __future__ import annotations

from typing import Optional

from .project import Project, load_project, save_project


def open_project(path: str) -> Project:
    """Wrapper around :func:`load_project`."""
    return load_project(path)


def save_project_file(project: Project, path: Optional[str] = None) -> None:
    """Save ``project`` to ``path`` if provided, else use ``project.path``."""
    if path is not None:
        project.path = path
    if not project.path:
        raise ValueError("Project path is not set")
    save_project(project, project.path)
