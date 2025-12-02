from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .pkg.models import ChannelSpec, DatasetMeta, Event, Sampling
from .pkg.package import VasoPackage


def cmd_new(args: argparse.Namespace) -> None:
    VasoPackage.create(args.path, title=args.title)
    print(f"Created {args.path}")


def cmd_add_dataset(args: argparse.Namespace) -> None:
    pkg = VasoPackage.open(args.path)
    meta = DatasetMeta(
        name=args.name,
        modality=args.modality,
        sampling=Sampling(rate_hz=args.rate),
        channels=[
            ChannelSpec(key=key, unit=unit) for key, unit in (kv.split(":") for kv in args.channels)
        ],
    )
    pkg.add_dataset(meta)
    print(f"Added dataset {meta.id}")


def cmd_add_event(args: argparse.Namespace) -> None:
    pkg = VasoPackage.open(args.path)
    event = Event(
        id=args.id,
        dataset_id=args.dataset_id,
        t=args.t,
        label=args.label,
        lane=args.lane,
    )
    pkg.add_event(event)
    print("Event added")


def cmd_pack(args: argparse.Namespace) -> None:
    pkg = VasoPackage.open(args.path)
    ref = pkg.pack_file_into_blobs(
        dataset_id=args.dataset_id,
        fs_path=args.file,
        role=args.role,
        mime=args.mime,
    )
    print(json.dumps(ref.model_dump(mode="json"), indent=2))


def cmd_verify(args: argparse.Namespace) -> None:
    pkg = VasoPackage.open(args.path)
    print(json.dumps(pkg.verify(), indent=2))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser("vaso")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("new")
    sp.add_argument("path")
    sp.add_argument("--title", default="")
    sp.set_defaults(func=cmd_new)

    sp = sub.add_parser("add-dataset")
    sp.add_argument("path")
    sp.add_argument("--name", required=True)
    sp.add_argument("--modality", default="diameter+pressure")
    sp.add_argument("--rate", type=float, required=True)
    sp.add_argument(
        "--channels",
        nargs="+",
        required=True,
        help="key:unit pairs",
    )
    sp.set_defaults(func=cmd_add_dataset)

    sp = sub.add_parser("add-event")
    sp.add_argument("path")
    sp.add_argument("--id", required=True)
    sp.add_argument("--dataset-id", required=True)
    sp.add_argument("--t", type=float, required=True)
    sp.add_argument("--label", required=True)
    sp.add_argument("--lane", default=None)
    sp.set_defaults(func=cmd_add_event)

    sp = sub.add_parser("pack")
    sp.add_argument("path")
    sp.add_argument("--dataset-id", required=True)
    sp.add_argument("--file", required=True)
    sp.add_argument("--role", default="tiff")
    sp.add_argument("--mime", default="image/tiff")
    sp.set_defaults(func=cmd_pack)

    sp = sub.add_parser("verify")
    sp.add_argument("path")
    sp.set_defaults(func=cmd_verify)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
