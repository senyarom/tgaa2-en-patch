#!/usr/bin/env python3
"""Create a fresh RomFS staging tree for a Court Record hook build."""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dgs2tool.arc import build_arc_bytes, parse_arc  # noqa: E402
from dgs2tool.gmd import build_gmd_bytes, parse_gmd_bytes  # noqa: E402
from dgs2tool.pagination import is_standard_dialogue_segment  # noqa: E402
from scripts.build_3ds_official_layout import (  # noqa: E402
    INTERACTIVE_TUTORIAL_FILE,
    INTERACTIVE_TUTORIAL_LABEL,
    OPENING_MOVIE_CAPTION_RE,
    OPENING_MOVIE_MAXIMUM_LINES,
    OPENING_MOVIE_MAXIMUM_WIDTH,
    line_width,
    read_3ds_advances,
    reflow_movie_subtitles,
    reflow_court_record_caption_adaptive,
    reflow_opening_movie_caption,
    reflow_tree,
    visible,
)
from scripts.patch_tgaa1_3ds_ui import apply_layout_overrides  # noqa: E402


TUTORIAL_RELATIVE_PATH = (
    Path("script") / "_output" / INTERACTIVE_TUTORIAL_FILE
)
INTERACTIVE_WAIT_RE = re.compile(r"<E027>.*?<E650(?:\s[^>]*)?>", re.DOTALL)
SPECIAL_WIDGET_RE = re.compile(r"<(E260|E521)(?:\s[^>]*)?>")
PAGE_LINE_LIMITS = {"E041": 2, "E260": 3, "E521": 3}
MOVIE_SUBTITLE_PATH = Path("msg") / "movie_subtitle_jpn.gmd"
MESSAGE_ARCHIVE_PATH = Path("archive") / "msg_cmn_jpn.arc"


def validate_movie_document(document: dict, source: str, widths: dict[int, int]) -> int:
    checked = 0
    for entry in document["entries"]:
        text = entry.get("text") or ""
        for page_index, segment in enumerate(text.split("<PAGE>")):
            lines = [line for line in visible(segment).splitlines() if line.strip()]
            if not lines:
                continue
            checked += 1
            measured = [line_width(line, widths) for line in lines]
            if (
                len(lines) > OPENING_MOVIE_MAXIMUM_LINES
                or max(measured) > OPENING_MOVIE_MAXIMUM_WIDTH
            ):
                raise RuntimeError(
                    f"movie text overflow in {source}:{entry.get('label')}:"
                    f"page {page_index}: lines={len(lines)}, widths={measured}"
                )
    return checked


def rebuild_and_validate_movie_text(
    romfs: Path,
    font: Path,
    *,
    apply_tgaa1_ui_overrides: bool = False,
    apply_tgaa2_court_record_layout: bool = False,
) -> tuple[int, int]:
    widths = read_3ds_advances(font)

    subtitle_path = romfs / MOVIE_SUBTITLE_PATH
    subtitle_report = reflow_movie_subtitles(
        subtitle_path,
        widths,
        OPENING_MOVIE_MAXIMUM_WIDTH,
    )
    if subtitle_report["overflow_entries"]:
        raise RuntimeError(f"movie subtitle overflow: {subtitle_report['overflows']}")
    subtitle_document = parse_gmd_bytes(subtitle_path.read_bytes())
    subtitle_pages = validate_movie_document(
        subtitle_document,
        str(subtitle_path),
        widths,
    )

    archive_path = romfs / MESSAGE_ARCHIVE_PATH
    archive = parse_arc(archive_path.read_bytes())
    replacements: dict[str, bytes] = {}
    opening_pages = 0
    opening_files = 0
    for item in archive["entries"]:
        filename = Path(item.name).name
        opening_caption = bool(OPENING_MOVIE_CAPTION_RE.fullmatch(filename))
        ui_override = apply_tgaa1_ui_overrides and filename == "UI_jpn.gmd"
        court_record = (
            apply_tgaa2_court_record_layout
            and filename in {"cast_caption_jpn.gmd", "evidence_caption_jpn.gmd"}
        )
        if not opening_caption and not ui_override and not court_record:
            continue
        document = parse_gmd_bytes(item.data)
        if opening_caption:
            opening_files += 1
            for entry in document["entries"]:
                text = entry.get("text")
                if text is None:
                    continue
                replacement, reports = reflow_opening_movie_caption(text, widths)
                overflows = [report for report in reports if report["status"] == "overflow"]
                if overflows:
                    raise RuntimeError(
                        f"opening movie overflow in {item.name}:{entry.get('label')}: "
                        f"{overflows}"
                    )
                if replacement != text:
                    entry["text"] = replacement
                    entry["text_hex"] = ""
        if ui_override:
            apply_layout_overrides(filename, document)
        if court_record:
            for entry in document["entries"]:
                text = entry.get("text")
                if text is None or entry.get("label") == "null":
                    continue
                entry["text"], _report = reflow_court_record_caption_adaptive(
                    text,
                    widths,
                )
                entry["text_hex"] = ""
        rebuilt = build_gmd_bytes(document)
        verified = parse_gmd_bytes(rebuilt)
        if opening_caption:
            opening_pages += validate_movie_document(
                verified,
                item.name,
                widths,
            )
        replacements[item.name] = rebuilt
    if opening_files == 0:
        raise RuntimeError(f"no opening movie GMDs found in {archive_path}")
    archive_path.write_bytes(build_arc_bytes(archive, replacements))
    return subtitle_pages, opening_pages


def validate_dialogue_widget_text(text: str, location: str) -> Counter[str]:
    checked: Counter[str] = Counter()
    for segment in text.split("<PAGE>"):
        kinds: list[str] = []
        if is_standard_dialogue_segment(segment):
            kinds.append("E041")
        kinds.extend(match.group(1) for match in SPECIAL_WIDGET_RE.finditer(segment))
        if not kinds:
            continue

        lines = [line for line in visible(segment).splitlines() if line.strip()]
        for kind in set(kinds):
            checked[kind] += 1
        exceeded = {
            kind: PAGE_LINE_LIMITS[kind]
            for kind in set(kinds)
            if len(lines) > PAGE_LINE_LIMITS[kind]
        }
        if exceeded:
            raise RuntimeError(
                f"overfull dialogue widget in {location}: "
                f"limits={exceeded}, lines={lines}"
            )
    return checked


def validate_dialogue_widgets(romfs: Path) -> Counter[str]:
    checked: Counter[str] = Counter()
    for path in sorted(romfs.rglob("*.gmd")):
        document = parse_gmd_bytes(path.read_bytes())
        for entry in document["entries"]:
            checked.update(
                validate_dialogue_widget_text(
                    entry.get("text") or "",
                    f"{path}:{entry.get('label')}",
                )
            )
    return checked


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
    parser.add_argument("--game", required=True, choices=("tgaa1", "tgaa2"))
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
    widgets = validate_dialogue_widgets(args.output_romfs)
    missing = {"E041", "E260", "E521"} - widgets.keys()
    if missing:
        raise RuntimeError(f"no pages found for: {', '.join(sorted(missing))}")
    print(
        "Validated dialogue widgets: "
        + ", ".join(
            f"{kind}={widgets[kind]} (max {PAGE_LINE_LIMITS[kind]} lines)"
            for kind in ("E041", "E260", "E521")
        )
    )
    subtitle_pages, opening_pages = rebuild_and_validate_movie_text(
        args.output_romfs,
        args.validation_font,
        apply_tgaa1_ui_overrides=args.game == "tgaa1",
        apply_tgaa2_court_record_layout=args.game == "tgaa2",
    )
    print(
        f"Validated movie text: subtitles={subtitle_pages}, "
        f"opening captions={opening_pages}."
    )


if __name__ == "__main__":
    main()
