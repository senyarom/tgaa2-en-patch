#!/usr/bin/env python3
"""Convert the raw GDB glyph probe log into a character-indexed CSV."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


GLYPH_PROBE = (
    " !\"#$%&'()*+,-./"
    "0123456789:;=?@"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`"
    "abcdefghijklmnopqrstuvwxyz{|}~"
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    rows: list[list[str]] = []
    for line in args.input.read_text().splitlines():
        fields = line.split(",")
        if len(fields) != 14 or not fields[0].isdigit():
            continue
        rows.append(fields)

    if len(rows) != len(GLYPH_PROBE):
        raise SystemExit(
            f"expected {len(GLYPH_PROBE)} glyphs, found {len(rows)}"
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(
            (
                "index",
                "codepoint",
                "character",
                "advance",
                "height",
                "x",
                "y",
                "glyph",
                "raw8",
                "rawc",
                "bearing_x",
                "bearing_y",
            )
        )
        for expected_index, (character, fields) in enumerate(
            zip(GLYPH_PROBE, rows, strict=True)
        ):
            actual_index = int(fields[0])
            if actual_index != expected_index:
                raise SystemExit(
                    f"expected index {expected_index}, found {actual_index}"
                )
            writer.writerow(
                (
                    actual_index,
                    f"U+{ord(character):04X}",
                    character,
                    fields[6],
                    fields[7],
                    fields[8],
                    fields[9],
                    fields[1],
                    fields[2],
                    fields[3],
                    fields[4],
                    fields[5],
                )
            )


if __name__ == "__main__":
    main()
