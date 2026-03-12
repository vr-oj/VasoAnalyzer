# VasoAnalyzer
# Copyright (c) 2025 Osvaldo J. Vega Rodriguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""MIME utilities for VasoAnalyzer drag-and-drop operations."""

from __future__ import annotations

import json

from PyQt6.QtCore import QByteArray, QMimeData

DATASET_MIME_TYPE = "application/x-vasoanalyzer-dataset"


def encode_dataset_mime(dataset_id: int, name: str = "") -> QMimeData:
    """Return a QMimeData encoding a dataset for drag operations."""
    mime = QMimeData()
    payload = json.dumps({"dataset_id": dataset_id, "name": name})
    mime.setData(DATASET_MIME_TYPE, QByteArray(payload.encode()))
    return mime


def decode_dataset_mime(mime: QMimeData) -> dict | None:
    """Decode dataset MIME data.

    Returns a dict with ``dataset_id`` (int) and ``name`` (str), or ``None``
    if the MIME data does not contain a valid encoded dataset.
    """
    if not mime.hasFormat(DATASET_MIME_TYPE):
        return None
    try:
        raw = bytes(mime.data(DATASET_MIME_TYPE)).decode()
        return json.loads(raw)
    except Exception:
        return None
