#!/usr/bin/env python3
"""Patch DGS2 SMDH or Add-On Content catalogue metadata."""

from __future__ import annotations

import argparse
from pathlib import Path

from dgs2tool.titlemeta import patch_dgs2_aoc_labels, patch_smdh_titles


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="format", required=True)

    smdh = subparsers.add_parser("smdh")
    smdh.add_argument("source", type=Path)
    smdh.add_argument("output", type=Path)
    smdh.add_argument("--short", required=True)
    smdh.add_argument("--long", required=True)
    smdh.add_argument("--publisher", default="CAPCOM")

    aoc = subparsers.add_parser("aoc")
    aoc.add_argument("source", type=Path)
    aoc.add_argument("output", type=Path)

    args = parser.parse_args()
    source = args.source.read_bytes()
    if args.format == "smdh":
        output = patch_smdh_titles(
            source,
            short_description=args.short,
            long_description=args.long,
            publisher=args.publisher,
        )
    else:
        output = patch_dgs2_aoc_labels(source)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(output)


if __name__ == "__main__":
    main()
