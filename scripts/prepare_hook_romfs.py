#!/usr/bin/env python3
"""Create a fresh RomFS staging tree for a Court Record hook build."""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dgs2tool.gmd import parse_gmd_bytes  # noqa: E402
from scripts.build_3ds_official_layout import (  # noqa: E402
    INTERACTIVE_TUTORIAL_FILE,
    INTERACTIVE_TUTORIAL_LABEL,
    line_width,
    read_3ds_advances,
    reflow_tree,
    visible,
)


TUTORIAL_RELATIVE_PATH = (
    Path("script") / "_output" / INTERACTIVE_TUTORIAL_FILE
)
INTERACTIVE_WAIT_RE = re.compile(r"<E027>.*?<E650(?:\s[^>]*)?>", re.DOTALL)


def validate_interactive_tutorials(
    romfs: Path,
    font: Path,
    maximum: int,
) -> int:
    widths = read_3ds_advances(font)
    checked = 0
    for path in sorted(romfs.rglob("*.gmd")):
        document = parse_gmd_bytes(path.read_bytes())
        for entry in document["entries"]:
            text = entry.get("text") or ""
            cross_page_waits = [
                match.group()
                for match in INTERACTIVE_WAIT_RE.finditer(text)
                if "<PAGE>" in match.group()
            ]
            if cross_page_waits:
                raise RuntimeError(
                    f"interactive wait crosses a page in {path}:{entry.get('label')}"
                )
            for segment in text.split("<PAGE>"):
                if not INTERACTIVE_WAIT_RE.search(segment):
                    continue
                checked += 1
                lines = [line for line in visible(segment).splitlines() if line.strip()]
                measured = [line_width(line, widths) for line in lines]
                if (
                    not lines
                    or len(lines) > 2
                    or max(measured) > maximum
                    or "<E023>" in segment
                ):
                    raise RuntimeError(
                        f"invalid interactive tutorial page in "
                        f"{path}:{entry.get('label')}: "
                        f"lines={len(lines)}, widths={measured}, maximum={maximum}"
                    )
    return checked


def rebuild_tgaa1_tutorial(
    clean_gmd: Path,
    output_gmd: Path,
    font: Path,
) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        staged_gmd = root / INTERACTIVE_TUTORIAL_FILE
        shutil.copy2(clean_gmd, staged_gmd)
        widths = read_3ds_advances(font)
        report = reflow_tree(
            root,
            widths,
            maximum=365,
            dialogue_maximum=265,
        )
        if report["overflow_pages"]:
            raise RuntimeError(
                f"TGAA1 tutorial layout has {report['overflow_pages']} overflow(s): "
                f"{report['overflows']}"
            )

        document = parse_gmd_bytes(staged_gmd.read_bytes())
        entry = next(
            item
            for item in document["entries"]
            if item.get("label") == INTERACTIVE_TUTORIAL_LABEL
        )
        text = entry["text"]
        for wait in range(3):
            segment = next(
                part
                for part in text.split("<PAGE>")
                if f"<E650 {wait}>" in part
            )
            lines = [line for line in visible(segment).splitlines() if line.strip()]
            measured = [line_width(line, widths) for line in lines]
            if len(lines) != 2 or max(measured) > 265 or "<E023>" in segment:
                raise RuntimeError(
                    f"invalid E650 {wait} tutorial page: "
                    f"lines={len(lines)}, widths={measured}"
                )
        output_gmd.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(staged_gmd, output_gmd)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_romfs", type=Path)
    parser.add_argument("output_romfs", type=Path)
    parser.add_argument("--tgaa1-tutorial-source", type=Path)
    parser.add_argument("--font", type=Path)
    parser.add_argument("--validation-font", required=True, type=Path)
    parser.add_argument("--dialogue-maximum", required=True, type=int)
    args = parser.parse_args()

    if args.output_romfs.resolve() == args.source_romfs.resolve():
        raise ValueError("source and output RomFS must differ")
    if args.output_romfs.exists():
        shutil.rmtree(args.output_romfs)
    shutil.copytree(args.source_romfs, args.output_romfs)

    if args.tgaa1_tutorial_source is not None:
        if args.font is None:
            raise ValueError("--font is required with --tgaa1-tutorial-source")
        rebuild_tgaa1_tutorial(
            args.tgaa1_tutorial_source,
            args.output_romfs / TUTORIAL_RELATIVE_PATH,
            args.font,
        )
    checked = validate_interactive_tutorials(
        args.output_romfs,
        args.validation_font,
        args.dialogue_maximum,
    )
    if checked == 0:
        raise RuntimeError("no interactive tutorial waits were found")
    print(f"Validated {checked} interactive tutorial page(s).")


if __name__ == "__main__":
    main()
