#!/usr/bin/env python3
"""Apply the manually authored DLC English ledger to the original GMD JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from translate_dlc_draft import PAGE_RE, replace_visible


def load_ledger(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        item = json.loads(line)
        key = item["key"]
        if key in result:
            raise ValueError(f"duplicate key on line {number}: {key}")
        result[key] = item["translation"]
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("ledger", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    translations = load_ledger(args.ledger)
    used: set[str] = set()
    for source_path in sorted(args.source.rglob("*.json")):
        relative = source_path.relative_to(args.source)
        document = json.loads(source_path.read_text(encoding="utf-8"))
        for entry_index, entry in enumerate(document["entries"]):
            parts = PAGE_RE.split(entry["text"])
            for part_index in range(0, len(parts), 2):
                key = f"{relative}:{entry_index}:{part_index}"
                translation = translations.get(key)
                if translation is None:
                    continue
                parts[part_index] = replace_visible(parts[part_index], translation)
                used.add(key)
            entry["text"] = "".join(parts)
            entry["text_hex"] = entry["text"].encode("utf-8").hex()
        output_path = args.output / relative
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    unknown = sorted(translations.keys() - used)
    if unknown:
        raise ValueError(f"{len(unknown)} ledger keys did not match the source; first: {unknown[0]}")
    print(f"applied {len(used)} direct translations")


if __name__ == "__main__":
    main()
