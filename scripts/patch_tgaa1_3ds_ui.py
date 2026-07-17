#!/usr/bin/env python3
"""Restore English translations for TGAA1's 3DS-only UI messages."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from dgs2tool.gmd import build_gmd_bytes, parse_gmd_bytes


JAPANESE_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
VISIBLE_UI_FILES = {
    "UI_jpn.gmd",
    "saveload_jpn.gmd",
    "system_jpn.gmd",
    "system_title_jpn.gmd",
    "title_jpn.gmd",
}

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("official_root", type=Path)
    parser.add_argument("scarlet_root", type=Path)
    parser.add_argument("output_root", type=Path)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()

    records = []
    for filename in sorted(VISIBLE_UI_FILES):
        official_path = args.official_root / filename
        scarlet_path = args.scarlet_root / filename
        official = parse_gmd_bytes(official_path.read_bytes())
        scarlet = parse_gmd_bytes(scarlet_path.read_bytes())
        scarlet_by_label = {entry.get("label"): entry for entry in scarlet["entries"]}

        replaced = []
        for entry in official["entries"]:
            current = entry.get("text") or ""
            if not JAPANESE_RE.search(current):
                continue
            replacement_entry = scarlet_by_label.get(entry.get("label"))
            replacement = (replacement_entry or {}).get("text") or ""
            if not replacement or JAPANESE_RE.search(replacement):
                raise ValueError(
                    f"no English 3DS fallback for {filename}:{entry.get('label')}"
                )
            entry["text"] = replacement
            entry["text_hex"] = ""
            replaced.append(entry.get("label"))

        output_blob = build_gmd_bytes(official)
        verified = parse_gmd_bytes(output_blob)
        remaining = [
            entry.get("label")
            for entry in verified["entries"]
            if JAPANESE_RE.search(entry.get("text") or "")
        ]
        if remaining:
            raise ValueError(f"Japanese UI remains in {filename}: {remaining}")
        destination = args.output_root / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(output_blob)
        records.append({"file": filename, "replaced": len(replaced), "labels": replaced})

    report = {
        "files_written": len(records),
        "entries_replaced": sum(record["replaced"] for record in records),
        "files": records,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
