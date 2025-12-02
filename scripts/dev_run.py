#!/usr/bin/env python3
"""Convenience launcher for local VasoAnalyzer development workflows."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from PyQt5.QtWidgets import QApplication

from vasoanalyzer.app import is_enabled
from vasoanalyzer.app import reload as reload_flags
from vasoanalyzer.app.flags import all_enabled
from vasoanalyzer.services.project_service import open_project_file
from vasoanalyzer.ui.main_window import VasoAnalyzerApp


def _apply_feature_overrides(raw: str | None) -> None:
    if raw is None:
        return
    os.environ["VA_FEATURES"] = raw
    reload_flags()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the VasoAnalyzer UI locally.")
    parser.add_argument(
        "--project",
        "-p",
        type=str,
        help="Path to a .vaso project to open on launch.",
    )
    parser.add_argument(
        "--features",
        "-f",
        metavar="FLAGS",
        help="Comma-separated list of feature flags (VA_FEATURES syntax).",
    )
    parser.add_argument(
        "--offscreen",
        action="store_true",
        help="Launch with QT_QPA_PLATFORM=offscreen (useful for CI / screenshots).",
    )
    args = parser.parse_args()

    if args.offscreen:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    _apply_feature_overrides(args.features)

    app = QApplication.instance() or QApplication([])
    window = VasoAnalyzerApp(check_updates=not args.offscreen)

    if args.project:
        project_path = Path(args.project).expanduser().resolve(strict=False)
        project = open_project_file(project_path.as_posix())
        window._replace_current_project(project)
        window.refresh_project_tree()
        if project.experiments and project.experiments[0].samples:
            sample = project.experiments[0].samples[0]
            window.load_sample_into_view(sample)

    window.show()

    active_flags = ", ".join(sorted(k for k, v in all_enabled().items() if v)) or "none"
    window.statusBar().showMessage(f"Active flags: {active_flags}", 4000)
    if is_enabled("dev_toolbar", default=False):
        window.toolbar.show()

    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
