#!/usr/bin/env python3
"""Apply concise TGAA1 wording required by the narrower 3DS presentation."""

from __future__ import annotations

import argparse
from pathlib import Path

from dgs2tool.gmd import build_gmd_bytes, parse_gmd_bytes


REPLACEMENTS = {
    ("_sce00_c000_0001_jpn.gmd", "L_START"): ("Supreme Court of Judicature, Defendants' Antechamber 5", "Supreme Court, Defendants' Antechamber 5"),
    ("_sce00_c007_0000_jpn.gmd", "L_START"): ("Supreme Court of Judicature, Defendants' Antechamber 5", "Supreme Court, Defendants' Antechamber 5"),
    ("_sce00_c016_0000_jpn.gmd", "L_START"): ("Supreme Court of Judicature, Defendants' Antechamber 5", "Supreme Court, Defendants' Antechamber 5"),
    ("_sce02_c000_0001_jpn.gmd", "L_START"): ("British Supreme Court, Lord Chief Justice's Office", "Supreme Court, Lord Chief Justice's Office"),
    ("_sce03_c000_0001_jpn.gmd", "L_START"): ("British Supreme Court, Lord Chief Justice's Office", "Supreme Court, Lord Chief Justice's Office"),
    ("_sce04_c101_0004_jpn.gmd", "L_START"): ("British Supreme Court, Lord Chief Justice's Office", "Supreme Court, Lord Chief Justice's Office"),
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    for (filename, label), (source, replacement) in REPLACEMENTS.items():
        path = args.root / filename
        document = parse_gmd_bytes(path.read_bytes())
        entry = next(item for item in document["entries"] if item.get("label") == label)
        text = entry.get("text") or ""
        if text.count(source) != 1:
            raise ValueError(f"expected one {source!r} in {path}:{label}")
        entry["text"] = text.replace(source, replacement)
        entry["text_hex"] = ""
        path.write_bytes(build_gmd_bytes(document))
    print(f"applied {len(REPLACEMENTS)} TGAA1 3DS wording replacements")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
