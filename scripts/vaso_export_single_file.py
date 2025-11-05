#!/usr/bin/env python3
"""CLI helper to export a shareable single-file .vaso project."""

from __future__ import annotations

import argparse

from vasoanalyzer.tools.portable_export import export_single_file


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a shareable single-file .vaso project")
    parser.add_argument("src", help="Path to the source .vaso project")
    parser.add_argument("-o", "--out", help="Destination .vaso (default: *.shareable.vaso)")
    parser.add_argument(
        "--no-link-tiffs",
        action="store_true",
        help="Do not externalize embedded TIFF snapshots",
    )
    parser.add_argument(
        "--extract-tiffs",
        metavar="DIR",
        help="Extract TIFF binaries to DIR/assets/<sha>.tif while exporting",
    )
    args = parser.parse_args()

    dest = export_single_file(
        args.src,
        out_path=args.out,
        link_snapshot_tiffs=not args.no_link_tiffs,
        extract_tiffs_dir=args.extract_tiffs,
    )
    print(dest)


if __name__ == "__main__":
    main()
