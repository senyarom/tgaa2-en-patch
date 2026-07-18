#!/usr/bin/env python3
"""Post-process English dialogue and location captions in TGAA1's 3DS DLC."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dgs2tool.gmd import build_gmd_bytes, parse_gmd_bytes
from dgs2tool.location_captions import compact_location_captions
from dgs2tool.pagination import dialogue_page_line_counts, paginate_dialogue_text
from scripts.build_3ds_official_layout import read_3ds_advances


ESCAPADE_RE = re.compile(r"sce07_c(?P<issue>\d{3})_0000_jpn\.gmd")


def target_files(root: Path) -> list[Path]:
    result: list[Path] = []
    for path in root.glob("contents.*/romfs/script/sce07_c*_0000_jpn.gmd"):
        match = ESCAPADE_RE.fullmatch(path.name)
        if match is not None and 0 <= int(match.group("issue")) <= 8:
            result.append(path)
    return sorted(result)


def paginate_file(
    path: Path,
    maximum_lines: int,
    widths: dict[int, int],
    maximum_caption_width: int,
    dry_run: bool,
) -> dict:
    document = parse_gmd_bytes(path.read_bytes())
    original_visible = [entry.get("text") for entry in document["entries"]]
    insertions: list[dict] = []
    changed_entries = 0
    before_overfull = 0
    captions: list[dict] = []

    for entry in document["entries"]:
        text = entry.get("text")
        if text is None:
            continue
        before_overfull += sum(count > maximum_lines for count in dialogue_page_line_counts(text))
        replacement, caption_reports = compact_location_captions(
            text, widths, maximum_caption_width
        )
        for report in caption_reports:
            report.update({"entry": entry["index"], "label": entry.get("label")})
            captions.append(report)
        replacement, reports = paginate_dialogue_text(replacement, maximum_lines)
        for report in reports:
            report.update({"entry": entry["index"], "label": entry.get("label")})
            insertions.append(report)
        if replacement != text:
            entry["text"] = replacement
            entry["text_hex"] = ""
            changed_entries += 1

    after_overfull = sum(
        count > maximum_lines
        for entry in document["entries"]
        if entry.get("text") is not None
        for count in dialogue_page_line_counts(entry["text"])
    )
    if after_overfull:
        raise ValueError(f"{path}: {after_overfull} dialogue pages still exceed the height limit")
    caption_overflows = [report for report in captions if report["status"] == "overflow"]
    if caption_overflows:
        raise ValueError(
            f"{path}: {len(caption_overflows)} location captions still exceed the width limit"
        )

    blob = build_gmd_bytes(document)
    verified = parse_gmd_bytes(blob)
    if [entry.get("text") for entry in verified["entries"]] != [
        entry.get("text") for entry in document["entries"]
    ]:
        raise ValueError(f"GMD round-trip verification failed: {path}")
    if len(original_visible) != len(verified["entries"]):
        raise ValueError(f"GMD entry count changed: {path}")
    if not dry_run and changed_entries:
        path.write_bytes(blob)

    return {
        "file": str(path),
        "entries": len(document["entries"]),
        "changed_entries": changed_entries,
        "overfull_pages_before": before_overfull,
        "inserted_pages": len(insertions),
        "overfull_pages_after": after_overfull,
        "location_captions": len(captions),
        "compacted_location_captions": sum(
            report["status"] == "reflowed" for report in captions
        ),
        "location_caption_overflows": len(caption_overflows),
        "location_caption_reports": captions,
        "examples": insertions[:10],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path, help="extracted DLC root containing contents.* directories")
    parser.add_argument("report", type=Path)
    parser.add_argument("--font", required=True, type=Path, help="adapted 3DS font00_jpn.gfd")
    parser.add_argument("--maximum-lines", type=int, default=2)
    parser.add_argument("--maximum-caption-width", type=int, default=372)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    paths = target_files(args.root)
    if len(paths) != 9:
        raise ValueError(f"expected special issue plus eight escapade scripts, found {len(paths)}")
    widths = read_3ds_advances(args.font)
    files = [
        paginate_file(
            path,
            args.maximum_lines,
            widths,
            args.maximum_caption_width,
            args.dry_run,
        )
        for path in paths
    ]
    report = {
        "maximum_dialogue_lines": args.maximum_lines,
        "dry_run": args.dry_run,
        "files": files,
        "summary": {
            "files": len(files),
            "changed_files": sum(bool(record["changed_entries"]) for record in files),
            "overfull_pages_before": sum(record["overfull_pages_before"] for record in files),
            "inserted_pages": sum(record["inserted_pages"] for record in files),
            "overfull_pages_after": sum(record["overfull_pages_after"] for record in files),
            "location_captions": sum(record["location_captions"] for record in files),
            "compacted_location_captions": sum(
                record["compacted_location_captions"] for record in files
            ),
            "location_caption_overflows": sum(
                record["location_caption_overflows"] for record in files
            ),
        },
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
