# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

from __future__ import annotations

import logging
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


def check_for_new_version(current_version: str = APP_VERSION) -> str | None:
    """
    Return the latest release tag if it differs from ``current_version``.

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
    if isinstance(latest_version, str) and latest_version and latest_version != current_version:
        return latest_version
    return None
