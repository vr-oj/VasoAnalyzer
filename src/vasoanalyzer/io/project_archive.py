# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Project file packing and unpacking utilities for VasoAnalyzer."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import zipfile
from typing import Any

import pandas as pd
from tifffile import imread, imwrite

from vasoanalyzer.core.project import _safe_extractall

__all__ = ["embed_tiff", "save_project", "open_project"]


THRESHOLD_BYTES = 1 * 1024**3  # 1 GiB


def embed_tiff(
    src_path: str, dest_dir: str, threshold_bytes: int = THRESHOLD_BYTES
) -> tuple[str, bool]:
    """Copy or compress ``src_path`` into ``dest_dir``.

    Parameters
    ----------
    src_path:
        Path to the source TIFF file.
    dest_dir:
        Directory inside the temporary project where the file should be placed.
    threshold_bytes:
        Size threshold at which the TIFF will be rewritten with LZW compression.

    Returns
    -------
    tuple[str, bool]
        The filename written and whether compression was applied.
    """

    size = os.path.getsize(src_path)
    fname = os.path.basename(src_path)
    out_path = os.path.join(dest_dir, fname)

    if size <= threshold_bytes:
        os.makedirs(dest_dir, exist_ok=True)
        shutil.copy2(src_path, out_path)
        compressed = False
    else:
        os.makedirs(dest_dir, exist_ok=True)
        stack = imread(src_path)
        imwrite(out_path, stack, compression="lzw")
        compressed = True

    return fname, compressed


def _write_json(path: str, data: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def save_project(
    path: str,
    experiments: dict[str, dict[str, Any]],
    state: dict[str, Any],
    exports: dict[str, str] | None = None,
) -> None:
    """Save a project to ``path`` using the .vaso format.

    Parameters
    ----------
    path:
        Destination ``.vaso`` file.
    experiments:
        Mapping of experiment IDs to dictionaries containing keys ``trace``
        and ``events``. ``trace`` and ``events`` should be
        :class:`pandas.DataFrame` objects. Snapshot TIFFs are no longer stored
        inside the project archive and will be ignored if provided.
    state:
        Arbitrary session state dictionary to be stored as ``state.json``.
    exports:
        Optional mapping of filename -> source path to include under the
        ``exports`` directory.
    """

    with tempfile.TemporaryDirectory() as tmpdir:
        manifest: dict[str, Any] = {"schema_version": "1.1", "experiments": {}}
        state = {"schema_version": "1.1", **state}

        exp_root = os.path.join(tmpdir, "experiments")
        os.makedirs(exp_root, exist_ok=True)

        for exp_id, exp_data in experiments.items():
            exp_dir = os.path.join(exp_root, exp_id)
            os.makedirs(exp_dir, exist_ok=True)

            trace_df: pd.DataFrame = exp_data.get("trace")
            events_df: pd.DataFrame = exp_data.get("events")
            events_user_df: pd.DataFrame | None = exp_data.get("events_user")
            tiff_path: str | None = exp_data.get("tiff")

            trace_file = os.path.join(exp_dir, "trace.csv")
            events_file = os.path.join(exp_dir, "events.csv")
            events_user_file = (
                os.path.join(exp_dir, "events_user.csv") if events_user_df is not None else None
            )
            trace_df.to_csv(trace_file, index=False)
            events_df.to_csv(events_file, index=False)
            if events_user_df is not None:
                events_user_df.to_csv(events_user_file, index=False)

            manifest_entry: dict[str, Any] = {
                "trace_file": f"experiments/{exp_id}/trace.csv",
                "events_file": f"experiments/{exp_id}/events.csv",
            }
            if events_user_df is not None:
                manifest_entry["events_user_file"] = f"experiments/{exp_id}/events_user.csv"
            if tiff_path:
                tiff_dir = os.path.join(exp_dir, "tiff")
                fname, compressed = embed_tiff(tiff_path, tiff_dir)
                manifest_entry["tiff_file"] = f"experiments/{exp_id}/tiff/{fname}"
                manifest_entry["tiff_compressed"] = compressed
            manifest["experiments"][exp_id] = manifest_entry

        _write_json(os.path.join(tmpdir, "manifest.json"), manifest)
        _write_json(os.path.join(tmpdir, "state.json"), state)

        if exports:
            exp_dir = os.path.join(tmpdir, "exports")
            os.makedirs(exp_dir, exist_ok=True)
            for fname, src in exports.items():
                shutil.copy2(src, os.path.join(exp_dir, fname))

        tmp_zip = f"{path}.tmp"
        with zipfile.ZipFile(tmp_zip, "w") as zf:
            for root, _dirs, files in os.walk(tmpdir):
                for file in files:
                    full = os.path.join(root, file)
                    rel = os.path.relpath(full, tmpdir)
                    zf.write(full, rel)
        os.replace(tmp_zip, path)


def open_project(path: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load ``path`` and return ``(manifest, state)``.

    Parameters
    ----------
    path:
        Path to the ``.vaso`` archive.

    Returns
    -------
    tuple
        ``manifest`` and ``state`` dictionaries with data loaded from CSV/TIFF
        files already populated.
    """

    tmpdir_manager = tempfile.TemporaryDirectory()
    tmpdir = tmpdir_manager.name

    with zipfile.ZipFile(path, "r") as zf:
        _safe_extractall(zf, tmpdir)

        with open(os.path.join(tmpdir, "manifest.json"), encoding="utf-8") as fh:
            manifest = json.load(fh)
        with open(os.path.join(tmpdir, "state.json"), encoding="utf-8") as fh:
            state = json.load(fh)

        for _exp_id, meta in manifest.get("experiments", {}).items():
            for key in ("trace_file", "events_file", "events_user_file", "tiff_file"):
                if key in meta:
                    meta[key] = os.path.join(tmpdir, meta[key])

        # Retain both the extracted path and the TemporaryDirectory manager so
        # callers can clean up once they finish loading the data.  The manager
        # keeps the directory alive for the duration of the manifest object.
        manifest["_tempdir"] = tmpdir
        manifest["_tempdir_manager"] = tmpdir_manager

    return manifest, state
