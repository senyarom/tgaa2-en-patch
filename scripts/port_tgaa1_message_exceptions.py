#!/usr/bin/env python3
"""Translate two small 3DS-only TGAA1 paired-reasoning label tables."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dgs2tool.gmd import build_gmd_bytes, parse_gmd_bytes


TRANSLATIONS = {
    "pair_reasoning_sce02_jpn.gmd": {
        "PAIR_REASONING_SCE02_000": "[Beard]",
        "PAIR_REASONING_SCE02_001": "[Coat]",
        "PAIR_REASONING_SCE02_002": "[Long Blond Hair]",
        "PAIR_REASONING_SCE02_003": "Chair",
        "PAIR_REASONING_SCE02_004": "[Tiara]",
        "PAIR_REASONING_SCE02_005": "[Trunk]",
        "PAIR_REASONING_SCE02_006": "Chair 2",
        "PAIR_REASONING_SCE02_007": "[Bookshelf]",
        "PAIR_REASONING_SCE02_008": "[Notice]",
    },
    "pair_reasoning_sce06_jpn.gmd": {
        "PAIR_REASONING_SCE06_000": "Splendid Beard",
        "PAIR_REASONING_SCE06_001": "Thick Coat",
        "PAIR_REASONING_SCE06_002": "Beautiful Blond Hair",
        "PAIR_REASONING_SCE06_003": " ",
        "PAIR_REASONING_SCE06_004": "Tiara",
        "PAIR_REASONING_SCE06_005": "Trunk",
        "PAIR_REASONING_SCE06_006": "Chair 2",
        "PAIR_REASONING_SCE06_007": "Bookshelf",
        "PAIR_REASONING_SCE06_008": "Notice",
    },
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_root", type=Path)
    parser.add_argument("output_root", type=Path)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()

    records = []
    for filename, translations in TRANSLATIONS.items():
        source = args.source_root / filename
        document = parse_gmd_bytes(source.read_bytes())
        labels = {entry.get("label") for entry in document["entries"]}
        if labels != set(translations):
            raise ValueError(f"label set changed in {source}")
        for entry in document["entries"]:
            entry["text"] = translations[entry["label"]]
            entry["text_hex"] = ""
        output_blob = build_gmd_bytes(document)
        verified = parse_gmd_bytes(output_blob)
        if {entry["label"]: entry["text"] for entry in verified["entries"]} != translations:
            raise ValueError(f"translation verification failed for {filename}")
        destination = args.output_root / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(output_blob)
        records.append({"file": filename, "entries": len(translations), "verified": True})

    report = {"files_written": len(records), "entries_written": sum(r["entries"] for r in records), "files": records}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
