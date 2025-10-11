# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Entry point for launching the VasoAnalyzer desktop application."""

from __future__ import annotations

import logging
import sys

from vasoanalyzer.app.launcher import VasoAnalyzerLauncher


def main(argv: list[str] | None = None) -> None:
    """Bootstrap the Qt application and block until it exits."""
    argv = list(sys.argv if argv is None else argv)
    project_path = argv[1] if len(argv) > 1 else None

    logging.basicConfig(level=logging.INFO)
    launcher = VasoAnalyzerLauncher(project_path=project_path)
    launcher.run()


if __name__ == "__main__":  # pragma: no cover - import guard
    main()
