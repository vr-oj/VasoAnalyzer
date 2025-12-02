# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

import json
import logging
import os
import pickle
from datetime import datetime
from pathlib import Path

from matplotlib import rcParams
from PyQt5.QtWidgets import QFileDialog, QMessageBox

from vasoanalyzer.ui.dialogs.figure_export_dialog import FigureExportDialog
from vasoanalyzer.ui.theme import CURRENT_THEME

log = logging.getLogger(__name__)


def auto_export_editable_plot(self):
    if not self.trace_file_path:
        return
    try:
        pickle_path = os.path.join(
            os.path.abspath(self.trace_file_path), "tracePlot_output.fig.pickle"
        )
        state = {
            "trace_data": self.trace_data,
            "event_labels": self.event_labels,
            "event_times": self.event_times,
            "event_table_data": self.event_table_data,
            "event_label_meta": getattr(self, "event_label_meta", []),
            "plot_style": self.get_current_plot_style(),
        }
        with open(pickle_path, "wb") as f:
            pickle.dump(state, f)
        log.info("Editable trace figure state saved to:\n%s", pickle_path)
    except Exception as e:
        log.error("Failed to save .pickle figure:\n%s", e)


def export_high_res_plot(self, checked: bool = False):
    """Export high-resolution plot.

    Args:
        checked: Unused boolean from Qt signal (ignored)
    """
    if not self.trace_file_path:
        QMessageBox.warning(self, "Export Error", "No trace file loaded.")
        return

    size_w, size_h = self.fig.get_size_inches()
    aspect_ratio = size_h / size_w if size_w else 0.6

    dialog = FigureExportDialog(self, default_format="tiff", aspect_ratio=aspect_ratio)
    if dialog.exec_() != dialog.Accepted:
        return

    settings = dialog.get_settings() or {}
    fmt = settings.get("format", "tiff")

    base_dir = os.path.abspath(self.trace_file_path)
    default_ext = ".svg" if fmt == "svg" else ".tiff"
    default_name = f"tracePlot_highres{default_ext}"

    filters = {
        "tiff": "TIFF Image (*.tiff *.tif)",
        "svg": "SVG Vector (*.svg)",
    }
    filter_string = ";;".join(filters.values())
    initial_filter = filters.get(fmt, filters["tiff"])

    save_path, _ = QFileDialog.getSaveFileName(
        self,
        "Save High-Resolution Plot",
        os.path.join(base_dir, default_name),
        filter_string,
        initial_filter,
    )

    if not save_path:
        return

    ext = Path(save_path).suffix.lower()
    if fmt == "svg" and ext != ".svg":
        save_path += ".svg"
    elif fmt == "tiff" and ext not in {".tif", ".tiff"}:
        save_path += ".tiff"

    try:
        if hasattr(self, "_ensure_style_manager"):
            manager = self._ensure_style_manager()
            manager.apply(
                ax=self.ax,
                ax_secondary=getattr(self, "ax2", None),
                event_text_objects=getattr(self, "event_text_objects", None),
                pinned_points=getattr(self, "pinned_points", None),
                main_line=self.ax.lines[0] if self.ax and self.ax.lines else None,
                od_line=getattr(self, "od_line", None),
            )

        original_size = self.fig.get_size_inches()
        original_dpi = self.fig.dpi
        width_mm = max(settings.get("width_mm", 120.0), 40.0)
        height_mm_default = width_mm * aspect_ratio
        height_mm = max(settings.get("height_mm", height_mm_default), 25.0)
        width_in = width_mm / 25.4
        height_in = height_mm / 25.4
        pad_inches = settings.get("pad_inches", 0.03)
        dpi = settings.get("dpi", 600)

        fonttype_backup = rcParams.get("svg.fonttype")
        if fmt == "svg":
            rcParams["svg.fonttype"] = "path" if settings.get("svg_flatten_fonts") else "none"

        self.fig.set_size_inches(width_in, height_in)

        save_kwargs = {
            "bbox_inches": "tight",
            "pad_inches": pad_inches,
        }

        if fmt == "svg":
            self.fig.savefig(save_path, format="svg", **save_kwargs)
        else:
            self.fig.savefig(save_path, format="tiff", dpi=dpi, **save_kwargs)
            self.auto_export_editable_plot()

        self._write_export_receipt(
            save_path,
            settings=settings,
            width_in=width_in,
            height_in=height_in,
            dpi=dpi,
        )

        QMessageBox.information(self, "Export Complete", f"Plot exported:\n{save_path}")
    except Exception as e:
        QMessageBox.critical(self, "Export Failed", str(e))
    finally:
        self.fig.set_size_inches(*original_size)
        self.fig.set_dpi(original_dpi)
        if fmt == "svg":
            rcParams["svg.fonttype"] = fonttype_backup
        self.canvas.draw_idle()


def toggle_grid(self):
    self.grid_visible = not self.grid_visible
    axes = []
    if hasattr(self, "plot_host"):
        axes = [axis for axis in self.plot_host.axes() if axis is not None]
    if not axes:
        axes = [getattr(self, "ax", None)]
    axes = [axis for axis in axes if axis is not None]
    for axis in axes:
        if self.grid_visible:
            axis.grid(True, color=CURRENT_THEME["grid_color"])
        else:
            axis.grid(False)
    self.canvas.draw_idle()


def _to_float_list(values):
    return [float(v) for v in values]


def _safe_getattr(obj, name, default=None):
    return getattr(obj, name, default)


def _serialize_pins(pins):
    serial = []
    for marker, _label in pins or []:
        try:
            serial.append(
                {
                    "time": float(marker.get_xdata()[0]),
                    "value": float(marker.get_ydata()[0]),
                    "trace": getattr(marker, "trace_type", "inner"),
                }
            )
        except (AttributeError, IndexError, TypeError, ValueError):
            # Skip markers with invalid data or missing attributes
            continue
    return serial


def _serialize_events(event_table):
    try:
        return len(event_table)
    except (TypeError, AttributeError):
        # event_table is None or doesn't support len()
        return 0


def _ensure_json_safe(value):
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): _ensure_json_safe(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_ensure_json_safe(v) for v in value]
    return str(value)


def _normalize_style(style_dict):
    if not isinstance(style_dict, dict):
        return {}
    return {k: _ensure_json_safe(v) for k, v in style_dict.items()}


def _write_export_receipt(self, save_path, settings, width_in, height_in, dpi):
    try:
        receipt_path = Path(f"{save_path}.json")
        metadata = {
            "exported_at": datetime.utcnow().isoformat() + "Z",
            "export": {
                "path": save_path,
                "format": settings.get("format"),
                "dpi": dpi,
                "width_mm": round(width_in * 25.4, 2),
                "height_mm": round(height_in * 25.4, 2),
                "pad_inches": settings.get("pad_inches", 0.03),
                "svg_flatten_fonts": settings.get("svg_flatten_fonts", False),
            },
            "axes": {
                "xlim": _to_float_list(self.ax.get_xlim()),
                "ylim": _to_float_list(self.ax.get_ylim()),
            },
            "grid_visible": bool(getattr(self, "grid_visible", True)),
            "style": _normalize_style(self.get_current_plot_style()),
            "source": {
                "trace_directory": getattr(self, "trace_file_path", None),
                "project": _safe_getattr(getattr(self, "current_project", None), "name"),
                "sample": _safe_getattr(getattr(self, "current_sample", None), "name"),
            },
            "events": {
                "count": _serialize_events(getattr(self, "event_table_data", [])),
            },
            "pins": _serialize_pins(getattr(self, "pinned_points", [])),
        }

        if getattr(self, "ax2", None) is not None:
            metadata["axes"]["y2lim"] = _to_float_list(self.ax2.get_ylim())

        with open(receipt_path, "w", encoding="utf-8") as fh:
            json.dump(metadata, fh, indent=2)
        log.info("Export receipt saved to %s", receipt_path)
    except Exception as exc:
        log.warning("Failed to write export receipt: %s", exc)
