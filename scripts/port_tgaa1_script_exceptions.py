#!/usr/bin/env python3
"""Port the four TGAA1 scripts whose PC and 3DS page layouts differ.

The normal batch porter deliberately rejects these files.  This script keeps
that strict default and documents the small, title-specific adaptations in one
auditable place.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

from dgs2tool.batch import _event_blocks, _merge_official_text, _segments
from dgs2tool.gmd import build_gmd_bytes, parse_gmd_bytes


EXCEPTIONS = {
    "_sce01_bg1101_3d_check_0_jpn.gmd": "scarlet_3ds_only_tiara",
    "_sce03_c102_0001_jpn.gmd": "drop_pc_only_opening_contention",
    "_sce03_c104_0003_jpn.gmd": "keep_empty_3ds_event",
    "_sce04_bg1500_3d_check_0_jpn.gmd": "replace_pc_cross_eye_instructions",
}


def _by_label(document: dict, source: Path) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for entry in document["entries"]:
        label = entry.get("label")
        if label is None or label in result:
            raise ValueError(f"invalid label in {source}: {label!r}")
        result[label] = entry
    return result


def _tailored_official_text(filename: str, label: str, official: str, scarlet: str) -> tuple[str, str]:
    if filename == "_sce01_bg1101_3d_check_0_jpn.gmd" and label == "L_BG1101_TIARA_0":
        # This examination dialogue exists only in the original 3DS release.
        return scarlet, "Scarlet Study text for 3DS-only dialogue"

    if filename == "_sce03_c102_0001_jpn.gmd" and label == "L_BOUTOU":
        segments = _segments(official)
        if len(segments) != 8:
            raise ValueError(f"unexpected PC contention layout: {len(segments)} segments")
        # Chronicles adds a first juror contention which is absent on 3DS.
        return "".join([segments[0], *segments[2:]]), "dropped PC-only first contention"

    if filename == "_sce03_c104_0003_jpn.gmd" and label == "L_EVI_START":
        # Both versions are visibly empty; only an empty PC page marker differs.
        return "", "kept visibly empty 3DS event"

    if filename == "_sce04_bg1500_3d_check_0_jpn.gmd" and label == "L_BG1500_STAND_S_SCOPE_0":
        official_segments = _segments(official)
        scarlet_segments = _segments(scarlet)
        if len(official_segments) != 25 or len(scarlet_segments) != 25:
            raise ValueError(
                "unexpected stereoscope layout: "
                f"official={len(official_segments)}, scarlet={len(scarlet_segments)}"
            )
        # PC pages 6-8 explain how to cross one's eyes, and page 13 repeats the
        # instruction.  Replace the three-page explanation with Scarlet's 3DS
        # slider instruction and omit the repeat.  The remaining 20 pages are
        # verbatim official English and align with the 21-page Japanese entry.
        selected = [
            official_segments[0],
            *official_segments[1:7],
            scarlet_segments[7],
            *official_segments[10:14],
            *official_segments[15:25],
        ]
        if len(selected) != 22:
            raise AssertionError(f"stereoscope adaptation produced {len(selected)} segments")
        return "".join(selected), "official PC text with 3DS slider instruction"

    return official, "official"


def _sha256(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def port_file(japanese_path: Path, official_path: Path, scarlet_path: Path, output_path: Path) -> dict:
    japanese_blob = japanese_path.read_bytes()
    official_blob = official_path.read_bytes()
    scarlet_blob = scarlet_path.read_bytes()
    japanese = parse_gmd_bytes(japanese_blob)
    official = parse_gmd_bytes(official_blob)
    scarlet = parse_gmd_bytes(scarlet_blob)
    official_by_label = _by_label(official, official_path)
    scarlet_by_label = _by_label(scarlet, scarlet_path)
    source_by_label = _by_label(japanese, japanese_path)
    output = copy.deepcopy(japanese)
    adaptations: list[dict] = []

    for entry in output["entries"]:
        label = entry["label"]
        if label not in official_by_label or label not in scarlet_by_label:
            raise ValueError(f"missing paired label {label} in {japanese_path.name}")
        official_text, source = _tailored_official_text(
            japanese_path.name,
            label,
            official_by_label[label]["text"] or "",
            scarlet_by_label[label]["text"] or "",
        )
        if source == "kept visibly empty 3DS event":
            adaptations.append({"label": label, "source": source})
            continue
        entry["text"], _merge_report = _merge_official_text(entry["text"] or "", official_text)
        entry["text_hex"] = ""
        if source != "official":
            adaptations.append({"label": label, "source": source})

    output_blob = build_gmd_bytes(output)
    verified = parse_gmd_bytes(output_blob)
    verified_by_label = _by_label(verified, output_path)
    for label, entry in verified_by_label.items():
        before = [match.group() for match in _event_blocks(source_by_label[label]["text"] or "")]
        after = [match.group() for match in _event_blocks(entry["text"] or "")]
        if after != before:
            raise ValueError(f"3DS event blocks changed in {japanese_path.name}: {label}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(output_blob)
    return {
        "file": japanese_path.name,
        "entries": len(output["entries"]),
        "adaptations": adaptations,
        "sha256": {
            "japanese_container": _sha256(japanese_blob),
            "official_english": _sha256(official_blob),
            "scarlet_reference": _sha256(scarlet_blob),
            "output_3ds": _sha256(output_blob),
        },
        "3ds_event_blocks_verified": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--japanese-root", type=Path, required=True)
    parser.add_argument("--official-root", type=Path, required=True)
    parser.add_argument("--scarlet-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    records = []
    for japanese_name in EXCEPTIONS:
        official_name = japanese_name.removesuffix("_jpn.gmd") + "_eng.gmd"
        records.append(
            port_file(
                args.japanese_root / japanese_name,
                args.official_root / official_name,
                args.scarlet_root / japanese_name,
                args.output_root / japanese_name,
            )
        )

    report = {
        "files_written": len(records),
        "3ds_event_blocks_verified": all(record["3ds_event_blocks_verified"] for record in records),
        "files": records,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
