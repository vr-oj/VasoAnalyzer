# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

from __future__ import annotations

import logging
import re
from typing import Final

import requests
from requests.exceptions import RequestException

from utils.config import APP_VERSION

log = logging.getLogger(__name__)

_API_URL: Final[str] = "https://api.github.com/repos/vr-oj/VasoAnalyzer/releases/latest"
_HEADERS: Final[dict[str, str]] = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "VasoAnalyzer Update Checker",
}

_VERSION_RE = re.compile(r"([\d.]+)(.*)")


def _parse_version_tag(tag: str) -> tuple[tuple[int, ...], bool]:
    """Parse a version tag like ``v3.0.0`` or ``v3.0.0 Beta`` into comparable parts.

    Returns ``(numeric_parts, is_stable)`` where *is_stable* is ``False``
    when the tag contains a pre-release suffix (e.g. Beta, alpha, rc1).
    """
    s = tag.strip().lstrip("vV")
    m = _VERSION_RE.match(s)
    if not m:
        return (0,), False
    parts: list[int] = []
    for p in m.group(1).split("."):
        try:
            parts.append(int(p))
        except ValueError:
            break
    is_stable = not bool(m.group(2).strip())
    return tuple(parts) if parts else (0,), is_stable


def is_newer_version(latest: str, current: str) -> bool:
    """Return ``True`` only if *latest* is strictly newer than *current*."""
    latest_parts, latest_stable = _parse_version_tag(latest)
    current_parts, current_stable = _parse_version_tag(current)

    if latest_parts > current_parts:
        return True
    if latest_parts < current_parts:
        return False
    # Same numeric version: a stable release is newer than a pre-release.
    return latest_stable and not current_stable


def check_for_new_version(current_version: str = APP_VERSION) -> str | None:
    """
    Return the latest release tag if it is *newer* than ``current_version``.

    Uses the GitHub releases API and never raises so callers can safely run it
    from worker threads.
    """

    try:
        response = requests.get(_API_URL, headers=_HEADERS, timeout=5)
        if response.status_code == requests.codes.ok:
            payload = response.json()
        elif response.status_code == requests.codes.not_modified:
            return None
        else:
            log.info("Update check skipped (status=%s)", response.status_code)
            return None
    except RequestException as exc:
        log.info("Update check failed: %s", exc)
        return None
    except ValueError as exc:
        log.info("Update check returned invalid JSON: %s", exc)
        return None

    latest_version = payload.get("tag_name")
    if (
        isinstance(latest_version, str)
        and latest_version
        and is_newer_version(latest_version, current_version)
    ):
        return latest_version
    return None
