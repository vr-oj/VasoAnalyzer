#!/usr/bin/env python3
"""
VasoAnalyzer Project Recovery Tool

Command-line utility for recovering corrupted projects.

Usage:
    python -m vasoanalyzer.cli.recover <project_path> [options]

Examples:
    # Automatic recovery (tries all methods)
    python -m vasoanalyzer.cli.recover MyProject.vasopack

    # List available recovery options
    python -m vasoanalyzer.cli.recover MyProject.vasopack --list

    # Extract specific snapshot
    python -m vasoanalyzer.cli.recover MyProject.vasopack --extract 42 --output recovered.vaso

    # Find autosave files
    python -m vasoanalyzer.cli.recover --find-autosaves ~/Documents
"""

import argparse
import sys
from pathlib import Path

from vasoanalyzer.utils.recovery import (
    extract_from_snapshot,
    find_autosave_files,
    list_recovery_options,
    recover_project,
)


def main():
    parser = argparse.ArgumentParser(
        description="VasoAnalyzer Project Recovery Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Automatic recovery
  %(prog)s MyProject.vasopack

  # List recovery options
  %(prog)s MyProject.vasopack --list

  # Extract specific snapshot
  %(prog)s MyProject.vasopack --extract 42 --output recovered.vaso

  # Find all autosave files
  %(prog)s --find-autosaves ~/Documents

For more help, see docs/BUNDLE_FORMAT.md
        """,
    )

    parser.add_argument(
        "project",
        nargs="?",
        help="Path to corrupted project (.vaso or .vasopack)",
    )

    parser.add_argument(
        "--list",
        action="store_true",
        help="List available recovery options without performing recovery",
    )

    parser.add_argument(
        "--extract",
        type=int,
        metavar="N",
        help="Extract snapshot N from bundle (requires --output)",
    )

    parser.add_argument(
        "--output",
        type=str,
        metavar="PATH",
        help="Output path for extracted snapshot",
    )

    parser.add_argument(
        "--find-autosaves",
        type=str,
        metavar="DIR",
        help="Find all autosave files in directory",
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed recovery progress",
    )

    args = parser.parse_args()

    # Configure logging
    import logging

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(levelname)s: %(message)s")
    else:
        logging.basicConfig(level=logging.INFO, format="%(message)s")

    # Find autosaves mode
    if args.find_autosaves:
        directory = Path(args.find_autosaves)
        if not directory.exists():
            print(f"Error: Directory not found: {directory}", file=sys.stderr)
            return 1

        print(f"Searching for autosave files in {directory}...")
        autosaves = find_autosave_files(directory)

        if not autosaves:
            print("No autosave files found.")
            return 0

        print(f"\nFound {len(autosaves)} autosave file(s):\n")
        for autosave in autosaves:
            print(f"  {autosave}")

        return 0

    # Require project path for other modes
    if not args.project:
        parser.print_help()
        return 1

    project_path = Path(args.project)

    if not project_path.exists():
        print(f"Error: Project not found: {project_path}", file=sys.stderr)
        return 1

    # List recovery options mode
    if args.list:
        options = list_recovery_options(project_path)
        print(f"\nRecovery options for: {project_path}")
        print(f"Format: {options['format']}\n")

        if not options["options"]:
            print("No recovery options available.")
            return 1

        print("Available recovery methods:\n")
        for i, opt in enumerate(options["options"], 1):
            available = "✓" if opt["available"] else "✗"
            print(f"{i}. [{available}] {opt['method']}")
            print(f"   {opt['description']}")

            if "snapshots" in opt:
                print(f"   Snapshots: {', '.join(map(str, opt['snapshots']))}")
            if "file" in opt:
                print(f"   File: {opt['file']}")
            if "files" in opt:
                print(f"   Files: {len(opt['files'])}")
            print()

        return 0

    # Extract snapshot mode
    if args.extract is not None:
        if not args.output:
            print("Error: --extract requires --output", file=sys.stderr)
            return 1

        output_path = Path(args.output)
        print(f"Extracting snapshot {args.extract} from {project_path}...")

        success = extract_from_snapshot(project_path, args.extract, output_path)

        if success:
            print(f"✓ Extracted to: {output_path}")
            return 0
        else:
            print(f"✗ Extraction failed", file=sys.stderr)
            return 1

    # Automatic recovery mode
    print(f"Attempting to recover: {project_path}\n")

    success, message, recovered_files = recover_project(project_path)

    if success:
        print(f"✓ Recovery succeeded!")
        print(f"  {message}")

        if recovered_files:
            print(f"\n  Recovered files:")
            for file in recovered_files:
                print(f"    - {file}")

        print(f"\nYou can now try opening: {project_path}")
        return 0
    else:
        print(f"✗ Recovery failed")
        print(f"  {message}")

        # Show available options
        print(f"\nTry these recovery options:")
        print(f"  1. Run with --list to see all available methods")
        print(f"  2. Check for autosave files: --find-autosaves {project_path.parent}")
        print(f"  3. If bundle format, try --extract with earlier snapshot number")
        print(f"  4. Check if .vaso.legacy backup exists")

        return 1


if __name__ == "__main__":
    sys.exit(main())
