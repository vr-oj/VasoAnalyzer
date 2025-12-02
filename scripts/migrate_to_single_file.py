#!/usr/bin/env python3
"""Bulk convert .vaso projects into shareable single-file copies."""

from __future__ import annotations

import argparse
from pathlib import Path

from vasoanalyzer.tools.portable_export import export_single_file


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bulk convert .vaso files to single-file DELETE mode"
    )
    parser.add_argument("root", help="Directory to scan for .vaso files")
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Rewrite matching .vaso files in place",
    )
    parser.add_argument(
        "--extract-tiffs",
        metavar="DIR",
        help="Extract embedded TIFF snapshots into DIR/assets/<sha>.tif",
    )
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve(strict=False)
    for path in root.rglob("*.vaso"):
        destination = (
            path if args.in_place else path.with_name(f"{path.stem}.shareable{path.suffix}")
        )
        export_single_file(
            str(path),
            out_path=str(destination),
            link_snapshot_tiffs=True,
            extract_tiffs_dir=args.extract_tiffs,
        )
        print(destination)


if __name__ == "__main__":
    main()
