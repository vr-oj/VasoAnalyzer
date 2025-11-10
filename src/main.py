# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Entry point for launching the VasoAnalyzer desktop application."""

from __future__ import annotations

import logging
import sys

from vasoanalyzer.app.launcher import VasoAnalyzerLauncher
from vasoanalyzer.core.logging_config import setup_production_logging

log = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> None:
    """Bootstrap the Qt application and block until it exits."""
    argv = list(sys.argv if argv is None else argv)
    project_path = argv[1] if len(argv) > 1 else None

    # Setup production logging with file rotation
    try:
        log_dir = setup_production_logging(app_name="VasoAnalyzer", console_level=logging.WARNING)
        log.info(f"VasoAnalyzer starting with project: {project_path or 'None'}")
    except Exception as e:
        # Fallback to basic logging if production logging fails
        logging.basicConfig(level=logging.INFO)
        log.error(f"Failed to setup production logging: {e}", exc_info=True)

    try:
        launcher = VasoAnalyzerLauncher(project_path=project_path)
        launcher.run()
        log.info("VasoAnalyzer exited normally")
    except Exception as e:
        log.critical(f"VasoAnalyzer crashed: {e}", exc_info=True)
        raise


if __name__ == "__main__":  # pragma: no cover - import guard
    main()
