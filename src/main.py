# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Entry point for launching the VasoAnalyzer desktop application."""

from __future__ import annotations

import logging
import os
import sys

if os.environ.get("VA_FAULTHANDLER", "1") != "0":
    import faulthandler

    faulthandler.enable()

log = logging.getLogger(__name__)


def _configure_sip_exit_behavior() -> None:
    for module_name in ("sip", "PyQt5.sip", "PyQt6.sip"):
        try:
            sip_module = __import__(module_name, fromlist=["setdestroyonexit"])
        except Exception:
            continue
        setter = getattr(sip_module, "setdestroyonexit", None)
        if callable(setter):
            try:
                setter(False)
            except Exception:
                pass
            break


def main(argv: list[str] | None = None) -> None:
    """Bootstrap the Qt application and block until it exits."""
    _configure_sip_exit_behavior()
    from vasoanalyzer.app.launcher import VasoAnalyzerLauncher
    from vasoanalyzer.core.logging_config import setup_production_logging
    from vasoanalyzer.core.single_instance import (
        SingleInstanceManager,
        collect_vaso_paths,
        queue_open_requests,
    )

    argv = list(sys.argv if argv is None else argv)
    vaso_paths = collect_vaso_paths(argv)
    project_path = vaso_paths[0] if vaso_paths else None
    if vaso_paths:
        queue_open_requests(vaso_paths)

    single_instance = SingleInstanceManager()
    if single_instance.forward_to_primary(vaso_paths):
        return

    # Setup production logging with file rotation and INFO console output
    try:
        log_dir = setup_production_logging(app_name="VasoAnalyzer", console_level=logging.INFO)
        print("=" * 70)
        print("VasoAnalyzer - Intuitive Vascular Analysis")
        print("=" * 70)
        log.info(f"Starting VasoAnalyzer with project: {project_path or 'None'}")
    except Exception as e:
        # Fallback to basic logging if production logging fails
        logging.basicConfig(level=logging.INFO)
        log.error(f"Failed to setup production logging: {e}", exc_info=True)

    # Clean up stale temp directories from crashed sessions
    try:
        from vasoanalyzer.storage.container_fs import cleanup_stale_temp_dirs

        cleaned = cleanup_stale_temp_dirs()
        if cleaned > 0:
            log.info(f"Cleaned up {cleaned} stale temp directories from previous sessions")
    except Exception as e:
        log.warning(f"Failed to clean up stale temp directories: {e}")

    try:
        launcher = VasoAnalyzerLauncher(project_path=project_path)
        single_instance.start_listening()
        launcher.run()
        log.info("VasoAnalyzer exited normally")
    except Exception as e:
        log.critical(f"VasoAnalyzer crashed: {e}", exc_info=True)
        raise


if __name__ == "__main__":  # pragma: no cover - import guard
    main()
