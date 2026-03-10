#!/usr/bin/env python3
"""Extract sample-related methods from main_window.py into SampleManager.

Run from project root:
    python scripts/extract_sample_manager.py
"""
import ast
import re
import textwrap
from pathlib import Path

MW = Path("src/vasoanalyzer/ui/main_window.py")
OUT = Path("src/vasoanalyzer/ui/managers/sample_manager.py")

TARGETS = [
    "_ensure_data_cache",
    "_update_sample_link_metadata",
    "_resolve_sample_link",
    "import_dataset_from_project_action",
    "import_dataset_package_action",
    "_gather_selected_samples_for_copy",
    "copy_selected_datasets",
    "paste_datasets",
    "_persist_sample_ui_state",
    "_get_sample_data_quality",
    "_update_tree_icons_for_samples",
    "_set_samples_data_quality",
    "_select_dataset_ids",
    "_select_tree_item_for_sample",
    "_selected_samples_from_tree",
    "_experiment_name_for_sample",
    "_open_first_sample_if_none_active",
    "_activate_sample",
    "on_sample_notes_changed",
    "on_sample_add_attachment",
    "on_sample_remove_attachment",
    "on_sample_open_attachment",
    "_queue_sample_load_until_context",
    "_flush_pending_sample_loads",
    "_log_sample_data_summary",
    "load_sample_into_view",
    "_prepare_sample_view",
    "_begin_sample_load_job",
    "_on_sample_load_finished",
    "_on_sample_load_error",
    "_render_sample",
    "add_sample",
    "add_sample_to_current_experiment",
    "load_data_into_sample",
    "_sample_values_at_time",
    "_start_sample_load_progress",
    "_update_sample_load_progress",
    "_finish_sample_load_progress",
    "_get_trace_model_for_sample",
    "sample_inner_diameter",
    "gather_ui_state",
    "_invalidate_sample_state_cache",
    "gather_sample_state",
    "apply_ui_state",
    "_sample_is_embedded",
    "apply_sample_state",
]


def extract():
    source = MW.read_text()
    lines = source.splitlines()
    tree = ast.parse(source)

    # Find VasoAnalyzerApp class
    cls = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "VasoAnalyzerApp":
            cls = node
            break
    assert cls is not None

    # Collect method ranges (1-indexed)
    methods = {}  # name -> (start_line_1idx, end_line_1idx, source_text)
    for item in cls.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name in TARGETS:
            start = item.lineno  # 1-indexed
            end = item.end_lineno  # 1-indexed inclusive
            text = "\n".join(lines[start - 1 : end])
            methods[item.name] = (start, end, text)

    missing = set(TARGETS) - set(methods.keys())
    if missing:
        print(f"WARNING: methods not found: {missing}")

    # --- Transform methods for SampleManager ---
    transformed = []
    for name in TARGETS:
        if name not in methods:
            continue
        _, _, text = methods[name]
        transformed.append(transform_method(text))

    # --- Build SampleManager file ---
    header = build_header()
    body_text = "\n\n".join(transformed)
    full = header + body_text + "\n"
    OUT.write_text(full)
    print(f"Wrote {OUT} ({len(full.splitlines())} lines)")

    # --- Replace methods in main_window.py with forwarding stubs ---
    # Work from bottom to top to preserve line numbers
    sorted_items = sorted(methods.items(), key=lambda x: x[1][0], reverse=True)
    new_lines = list(lines)  # mutable copy

    for name, (start, end, text) in sorted_items:
        stub = generate_stub(name, text)
        # Replace lines[start-1:end] with stub lines
        new_lines[start - 1 : end] = stub.splitlines()

    MW.write_text("\n".join(new_lines) + "\n")
    print(f"Updated {MW} ({len(new_lines)} lines)")


def transform_method(text: str) -> str:
    """Transform a method from main_window self-access to h = self._host access."""
    mlines = text.splitlines()

    # Find the def line and extract signature
    def_idx = 0
    for i, line in enumerate(mlines):
        if line.strip().startswith("def ") or line.strip().startswith("async def "):
            def_idx = i
            break

    # Find where the def signature ends (handle multi-line defs)
    sig_end = def_idx
    if not mlines[def_idx].rstrip().endswith(":"):
        for j in range(def_idx + 1, len(mlines)):
            if mlines[j].rstrip().endswith(":"):
                sig_end = j
                break

    # Find where the docstring ends (or where body starts)
    body_start = sig_end + 1
    # Skip docstring
    stripped = mlines[body_start].strip() if body_start < len(mlines) else ""
    if stripped.startswith('"""') or stripped.startswith("'''"):
        quote = stripped[:3]
        if stripped.count(quote) >= 2:
            # Single-line docstring
            body_start += 1
        else:
            # Multi-line docstring
            for j in range(body_start + 1, len(mlines)):
                if quote in mlines[j]:
                    body_start = j + 1
                    break

    # Insert h = self._host after docstring
    indent = "        "  # 8 spaces for method body in class
    h_line = f"{indent}h = self._host"

    result = mlines[: body_start] + [h_line] + mlines[body_start:]

    # Join and do replacements
    text = "\n".join(result)

    # Replace self.xxx with h.xxx (but not self._host, self._sample_mgr, etc.)
    # First, protect 'self' in def signature and 'self._host'
    text = do_self_replacements(text)

    return text


def do_self_replacements(text: str) -> str:
    """Replace self references with h references in method body."""
    lines = text.splitlines()
    result = []
    in_def = True  # first line is def, skip it

    for i, line in enumerate(lines):
        stripped = line.strip()
        # Skip the def line itself
        if i == 0 or (in_def and (stripped.startswith("def ") or stripped.startswith("async def ") or stripped.startswith("@"))):
            result.append(line)
            if stripped.startswith("def ") or stripped.startswith("async def "):
                in_def = False
            continue

        # Skip the h = self._host line
        if stripped == "h = self._host":
            result.append(line)
            continue

        # Replace patterns
        line = replace_self_in_line(line)
        result.append(line)

    return "\n".join(result)


def replace_self_in_line(line: str) -> str:
    """Replace self.xxx, getattr(self, ...), hasattr(self, ...), etc."""
    # getattr(self, -> getattr(h,
    line = line.replace("getattr(self,", "getattr(h,")
    line = line.replace("getattr(self)", "getattr(h)")
    # hasattr(self, -> hasattr(h,
    line = line.replace("hasattr(self,", "hasattr(h,")
    # setattr(self, -> setattr(h,
    line = line.replace("setattr(self,", "setattr(h,")
    # isinstance(self, -> isinstance(h,  (unlikely but safe)
    # id(self) -> id(h)  (unlikely but safe)
    line = line.replace("id(self)", "id(h)")

    # QMessageBox.xxx(self, -> QMessageBox.xxx(h,
    line = re.sub(r"QMessageBox\.(\w+)\(self,", r"QMessageBox.\1(h,", line)
    line = re.sub(r"QMessageBox\.(\w+)\(\s*self\s*,", r"QMessageBox.\1(h,", line)
    # QInputDialog.xxx(self, -> QInputDialog.xxx(h,
    line = re.sub(r"QInputDialog\.(\w+)\(self,", r"QInputDialog.\1(h,", line)
    # QFileDialog.xxx(self, -> QFileDialog.xxx(h,
    line = re.sub(r"QFileDialog\.(\w+)\(self,", r"QFileDialog.\1(h,", line)

    # Standalone self, on its own line (as parent arg in multi-line calls)
    stripped = line.strip()
    if stripped == "self," or stripped == "self":
        line = line.replace("self", "h")

    # self.xxx -> h.xxx (general case, but not self._host)
    # Use negative lookbehind for word chars and negative lookahead for _host
    line = re.sub(r"(?<!\w)self\.(?!_host\b)", "h.", line)

    return line


def generate_stub(name: str, text: str) -> str:
    """Generate a forwarding stub for the method."""
    mlines = text.splitlines()

    # Collect decorators and def line
    header_lines = []
    def_line_idx = 0
    for i, line in enumerate(mlines):
        if line.strip().startswith("@"):
            header_lines.append(line)
        elif line.strip().startswith("def ") or line.strip().startswith("async def "):
            header_lines.append(line)
            def_line_idx = i
            break

    # Handle multi-line def
    if not mlines[def_line_idx].rstrip().endswith(":"):
        for j in range(def_line_idx + 1, len(mlines)):
            header_lines.append(mlines[j])
            if mlines[j].rstrip().endswith(":"):
                def_line_idx = j
                break

    # Extract parameter names for forwarding call
    # Parse just the def to get args
    def_text = "\n".join(header_lines)
    # Add a pass body for parsing
    parse_text = def_text + "\n        pass"
    try:
        parsed = ast.parse(textwrap.dedent(parse_text))
        func = parsed.body[0]
        args = func.args

        # Build forwarding args (skip 'self')
        fwd_args = []
        all_arg_names = [a.arg for a in args.args[1:]]  # skip self
        # positional args
        for a in args.args[1:]:
            fwd_args.append(a.arg)
        # *args
        if args.vararg:
            fwd_args.append(f"*{args.vararg.arg}")
        # keyword-only
        for a in args.kwonlyargs:
            fwd_args.append(f"{a.arg}={a.arg}")
        # **kwargs
        if args.kwarg:
            fwd_args.append(f"**{args.kwarg.arg}")

        args_str = ", ".join(fwd_args)
    except Exception:
        args_str = ""

    # Check if method has return value by scanning for 'return' with a value
    has_return = False
    for line in mlines[def_line_idx + 1:]:
        stripped = line.strip()
        if stripped.startswith("return ") and stripped != "return None" and stripped != "return":
            has_return = True
            break

    indent = "        "
    prefix = "return " if has_return else ""
    call = f"{prefix}self._sample_mgr.{name}({args_str})"

    stub_lines = header_lines + [f"{indent}{call}"]
    return "\n".join(stub_lines)


def build_header() -> str:
    return '''# VasoAnalyzer
# Copyright (c) 2025 Osvaldo J. Vega Rodriguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""SampleManager -- sample lifecycle logic extracted from VasoAnalyzerApp."""

from __future__ import annotations

import contextlib
import copy
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd
from PyQt5.QtCore import QByteArray, QObject, QTimer, Qt
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (
    QApplication,
    QFileDialog,
    QInputDialog,
    QMessageBox,
    QTreeWidgetItem,
)

if TYPE_CHECKING:
    from vasoanalyzer.ui.main_window import VasoAnalyzerApp

log = logging.getLogger(__name__)


class SampleManager(QObject):
    """Manages sample lifecycle: loading, activation, state gather/apply."""

    def __init__(self, host: "VasoAnalyzerApp", parent: QObject | None = None):
        super().__init__(parent)
        self._host = host

'''


if __name__ == "__main__":
    extract()
