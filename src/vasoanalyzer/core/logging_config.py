# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Production-grade logging configuration with file rotation."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_production_logging(
    app_name: str = "VasoAnalyzer", console_level: int = logging.INFO
) -> Path:
    """
    Configure production-grade logging with file rotation.

    Creates two log files:
    - vasoanalyzer.log: All INFO+ messages (10 MB per file, 5 rotations = 50 MB total)
    - errors.log: ERROR+ messages only (5 MB per file, 3 rotations = 15 MB total)

    Args:
        app_name: Application name for log directory
        console_level: Minimum level for console output (default: WARNING)

    Returns:
        Path to the log directory
    """
    # Determine platform-specific log directory
    log_dir = _get_log_directory(app_name)
    log_dir.mkdir(parents=True, exist_ok=True)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Remove any existing handlers (in case this is called multiple times)
    root_logger.handlers.clear()

    # Create formatters
    detailed_formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    simple_formatter = logging.Formatter("%(levelname)-8s | %(name)s | %(message)s")

    # Main vasoanalyzer logger captures all package logs
    vaso_logger = logging.getLogger("vasoanalyzer")
    vaso_logger.setLevel(logging.DEBUG)
    vaso_logger.handlers.clear()

    # Main application log (DEBUG and above)
    app_log_path = log_dir / "vasoanalyzer.log"
    app_handler = RotatingFileHandler(
        app_log_path,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    app_handler.setLevel(logging.DEBUG)
    app_handler.setFormatter(detailed_formatter)
    vaso_logger.addHandler(app_handler)

    # Error-only log (easier to scan for problems)
    error_log_path = log_dir / "errors.log"
    error_handler = RotatingFileHandler(
        error_log_path,
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=3,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(detailed_formatter)
    root_logger.addHandler(error_handler)

    # Console output (configurable level, default INFO+)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(console_level)
    console_handler.setFormatter(simple_formatter)
    vaso_logger.addHandler(console_handler)

    # Reduce console noise from chatty modules; DEBUG still goes to file
    noisy_modules = [
        "vasoanalyzer.storage.project_storage",
        "vasoanalyzer.storage.bundle_adapter",
        "vasoanalyzer.storage.snapshots",
        "vasoanalyzer.storage.container_fs",
        "vasoanalyzer.storage.sqlite_store",
        "vasoanalyzer.core.project",
        "vasoanalyzer.core.file_lock",
    ]
    for name in noisy_modules:
        logging.getLogger(name).setLevel(logging.WARNING)

    # Ensure plotting modules emit DEBUG logs (e.g., [RANGE DEBUG] helpers)
    plot_logger = logging.getLogger("vasoanalyzer.ui.plots")
    plot_logger.setLevel(logging.DEBUG)

    trace_view_logger = logging.getLogger("vasoanalyzer.ui.trace_view")
    trace_view_logger.setLevel(logging.DEBUG)

    # Enable DEBUG logs for the figure composer to verify canvas initialization and memory
    composer_logger = logging.getLogger("vasoanalyzer.ui.mpl_composer.composer_window")
    composer_logger.setLevel(logging.DEBUG)

    # Log startup message
    log = logging.getLogger(__name__)
    log.info("=" * 70)
    log.info(f"{app_name} logging initialized")
    log.info(f"Log directory: {log_dir}")
    log.info(f"Main log: {app_log_path}")
    log.info(f"Error log: {error_log_path}")
    log.info(f"Platform: {sys.platform}, Python: {sys.version.split()[0]}")
    log.info("=" * 70)

    return log_dir


def _get_log_directory(app_name: str) -> Path:
    """
    Get platform-specific log directory.

    - Windows: %LOCALAPPDATA%\\AppName\\logs
    - macOS: ~/Library/Logs/AppName
    - Linux: ~/.local/share/AppName/logs
    """
    home = Path.home()

    if sys.platform == "win32":
        # Windows: Use AppData\Local
        base = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        return base / app_name / "logs"

    elif sys.platform == "darwin":
        # macOS: Use ~/Library/Logs
        return home / "Library" / "Logs" / app_name

    else:
        # Linux/Unix: Use XDG Base Directory Specification
        xdg_data_home = os.environ.get("XDG_DATA_HOME", home / ".local" / "share")
        return Path(xdg_data_home) / app_name / "logs"


def get_log_directory(app_name: str = "VasoAnalyzer") -> Path:
    """
    Get the log directory path without setting up logging.

    Useful for displaying log location to users or opening log folder.
    """
    return _get_log_directory(app_name)


# Import os for environment variables
import os
