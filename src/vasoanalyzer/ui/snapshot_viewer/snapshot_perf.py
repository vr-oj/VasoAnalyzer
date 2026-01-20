# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Snapshot performance logging helpers (opt-in via env var)."""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)
_PERF_SAMPLE_EVERY = 10
_perf_counts: dict[str, int] = {}


def _perf_mode() -> str:
    value = os.environ.get("VASO_DEBUG_SNAPSHOT_PERF", "").strip().lower()
    if not value:
        return "off"
    if value in {"0", "false", "no", "off"}:
        return "off"
    if value in {"1", "full", "all"}:
        return "full"
    return "sample"


def perf_enabled() -> bool:
    """Return True when snapshot perf logging is enabled."""
    return _perf_mode() != "off"


def log_perf(label: str, **fields) -> None:
    """Emit a perf log entry with compact key/value fields."""
    mode = _perf_mode()
    if mode == "off":
        return
    if mode == "sample":
        count = _perf_counts.get(label, 0) + 1
        _perf_counts[label] = count
        if count % _PERF_SAMPLE_EVERY != 0:
            return
    clean = {k: v for k, v in fields.items() if v is not None}
    payload = ", ".join(f"{k}={v}" for k, v in clean.items())
    if payload:
        log.info("[SNAPSHOT_PERF] %s %s", label, payload)
    else:
        log.info("[SNAPSHOT_PERF] %s", label)
