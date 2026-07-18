#!/usr/bin/env python3
"""Apply the manually authored English translation of TGAA1 DLC Issue 0."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dgs2tool.batch import _event_blocks, _segments, _visible_text
from dgs2tool.gmd import build_gmd_bytes, parse_gmd_bytes


TAG_RE = re.compile(r"<[^<>]*>")
RUBY_RE = re.compile(
    r"(?:<E507[^>]*>)?<RUBY><RB>(.*?)</RB><RT>.*?</RT></RUBY>(?:<E519>)?",
    re.DOTALL,
)
JP_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uff01-\uff60]")


def replace_visible(block: str, translation: str) -> str:
    block = RUBY_RE.sub(lambda match: match.group(1), block)
    pieces = TAG_RE.split(block)
    tags = TAG_RE.findall(block)
    candidates = [
        index
        for index, piece in enumerate(pieces)
        if piece.replace("\u3000", " ").strip()
    ]
    if not candidates:
        raise ValueError("translation targets an empty 3DS text segment")
    pieces[candidates[0]] = translation
    for index in candidates[1:]:
        pieces[index] = ""
    output: list[str] = []
    for index, piece in enumerate(pieces):
        output.append(piece)
        if index < len(tags):
            output.append(tags[index])
    return "".join(output)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("translations", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()

    document = parse_gmd_bytes(args.source.read_bytes())
    source_by_label = {entry["label"]: entry["text"] or "" for entry in document["entries"]}
    translations = json.loads(args.translations.read_text(encoding="utf-8"))
    used_labels: set[str] = set()
    translated_segments = 0

    for entry in document["entries"]:
        label = entry["label"]
        authored = translations.get(label)
        if authored is None:
            continue
        segments = _segments(entry["text"] or "")
        visible_indexes = [index for index, segment in enumerate(segments) if _visible_text(segment).strip()]
        if len(visible_indexes) != len(authored):
            raise ValueError(
                f"translation count differs for {label}: 3DS={len(visible_indexes)}, English={len(authored)}"
            )
        for index, translation in zip(visible_indexes, authored):
            segments[index] = replace_visible(segments[index], translation)
            translated_segments += 1
        entry["text"] = "".join(segments)
        entry["text_hex"] = ""
        used_labels.add(label)

    if used_labels != set(translations):
        raise ValueError(f"unknown translation labels: {sorted(set(translations) - used_labels)}")
    output_blob = build_gmd_bytes(document)
    verified = parse_gmd_bytes(output_blob)
    verified_by_label = {entry["label"]: entry["text"] or "" for entry in verified["entries"]}
    for label, source_text in source_by_label.items():
        before = [match.group() for match in _event_blocks(source_text)]
        after = [match.group() for match in _event_blocks(verified_by_label[label])]
        if before != after:
            raise ValueError(f"3DS event blocks changed in {label}")
    remaining = sorted(
        label for label in translations if JP_RE.search(_visible_text(verified_by_label[label]))
    )
    if remaining:
        raise ValueError(f"Japanese text remains in translated labels: {remaining}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(output_blob)
    report = {
        "labels_translated": len(used_labels),
        "segments_translated": translated_segments,
        "japanese_text_remaining": False,
        "3ds_event_blocks_verified": True,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
