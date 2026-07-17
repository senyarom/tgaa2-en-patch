#!/usr/bin/env python3
"""Port the official Chronicles English into TGAA1's eight 3DS escapades."""

from __future__ import annotations

import argparse
import copy
import json
import re
from pathlib import Path

from dgs2tool.batch import _event_blocks, _merge_official_text, _visible_text
from dgs2tool.gmd import build_gmd_bytes, parse_gmd_bytes


MOVIE_TITLES = {
    1: ("The Great Special Trial 2014", None),
    2: ("Jump Festa Exhibition Video", None),
    3: ("Episode 1 Commentary", None),
    4: ("Episode 2 Commentary", None),
    5: ("Episode 3 Commentary", None),
    6: ("Episode 4 Commentary", None),
    7: ("Episode 5 Commentary", "Special Video: Music"),
    8: ("Special Video: Sound Effects", None),
}

VOICE_SLOTS = {
    1: (1, 3, 4, 5, 6, 7),
    2: (8, 9, 10, 11, 12, 13),
    3: (14, 15, 16, 17, 18, 19),
    4: (20, 21, 22, 23, 24, 25),
    5: (26, 27, 28, 29, 30, 31),
    6: (32, 33, 34, 35, 36, 37),
    7: (),
    8: (),
}

COMMENT_OVERRIDES = {
    6: (
        "I began composing this without seeing the visuals, drawing on the opening music of the "
        "first Phoenix Wright: Ace Attorney. But the solemn majesty of the in-game graphics made "
        "it a poor fit, so it was dropped! – Maeba"
    ),
    38: (
        "The pizzicato creates a warm feeling, but this piece needed to capture the delight of "
        "arriving at Sholmes's home. Only after adding a more upbeat feel was the final composition "
        "accepted. – Kitagawa"
    ),
}

JP_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uff01-\uff60]")


def _labels(document: dict) -> dict[str, dict]:
    return {entry["label"]: entry for entry in document["entries"]}


def _text_map(path: Path) -> dict[str, str]:
    document = parse_gmd_bytes(path.read_bytes())
    return {entry["label"]: _visible_text(entry.get("text") or "") for entry in document["entries"]}


def _set_plain(entry: dict, text: str) -> None:
    if "<" in (entry.get("text") or ""):
        raise ValueError(f"expected plain metadata text in {entry['label']}")
    entry["text"] = text
    entry["text_hex"] = ""


def _set_raw(entry: dict, text: str) -> None:
    entry["text"] = text
    entry["text_hex"] = ""


def port_script(japanese_path: Path, official_path: Path, output_path: Path) -> dict:
    japanese = parse_gmd_bytes(japanese_path.read_bytes())
    official = parse_gmd_bytes(official_path.read_bytes())
    official_by_label = _labels(official)
    source_by_label = _labels(japanese)
    output = copy.deepcopy(japanese)
    text_segments = 0
    for entry in output["entries"]:
        source = official_by_label.get(entry["label"])
        if source is None:
            raise ValueError(f"official DLC label missing: {entry['label']}")
        entry["text"], report = _merge_official_text(entry.get("text") or "", source.get("text") or "")
        entry["text_hex"] = ""
        text_segments += report["text_segments"]

    blob = build_gmd_bytes(output)
    verified = parse_gmd_bytes(blob)
    for entry in verified["entries"]:
        before = [m.group() for m in _event_blocks(source_by_label[entry["label"]]["text"] or "")]
        after = [m.group() for m in _event_blocks(entry["text"] or "")]
        if before != after:
            raise ValueError(f"3DS DLC events changed: {japanese_path.name}:{entry['label']}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(blob)
    return {"entries": len(output["entries"]), "text_segments": text_segments, "3ds_events_verified": True}


def port_metadata(
    issue: int,
    source_path: Path,
    music: dict[str, str],
    escapades: dict[str, str],
    output_path: Path,
) -> dict:
    document = parse_gmd_bytes(source_path.read_bytes())
    entries = _labels(document)
    _set_plain(entries["TITLE"], f"Issue No. {issue}")

    first_music = 5 + (issue - 1) * 6
    for local_index in range(1, 7):
        official_index = first_music + local_index - 1
        for field in ("TITLE", "CONTENT", "COMMENT"):
            value = music[f"BGM{official_index}_{field}"]
            if field == "COMMENT" and official_index in COMMENT_OVERRIDES:
                value = COMMENT_OVERRIDES[official_index]
            _set_plain(entries[f"BGM{local_index}_{field}"], value)

    special_index = 52 + issue
    for field in ("TITLE", "CONTENT", "COMMENT"):
        _set_plain(entries[f"BGM7_{field}"], music[f"BGM{special_index}_{field}"])
    for field in ("TITLE", "CONTENT", "COMMENT"):
        _set_plain(entries[f"BGM8_{field}"], "Unused")

    composer_names = {"北川": "Kitagawa", "前馬": "Maeba", "山東": "Sando"}
    for local_index in range(1, 9):
        label = f"BGM{local_index}_COMPOSER"
        if label in entries:
            original = _visible_text(entries[label].get("text") or "").strip()
            _set_plain(entries[label], composer_names.get(original, ""))

    active_voices = VOICE_SLOTS[issue]
    for local_index in range(1, 21):
        label = f"VOICE{local_index:02}_TITLE"
        if local_index <= len(active_voices):
            value = music[f"VOICE{active_voices[local_index - 1]:02}_TITLE"]
        else:
            value = "Unused"
        _set_plain(entries[label], value)

    title = escapades[f"EXTRA_TITLE_{issue:02}"]
    _set_raw(
        entries["OMNIBUS_START"],
        f'<CHOI 2 0 1><CLS>Start {title}?\r\n'
        '<RGB AA0B0B>* Contains spoilers for the main story.</RGB>',
    )
    movie1, movie2 = MOVIE_TITLES[issue]
    _set_raw(entries["MOVIE1_START"], f'<CHOI 2 0 1><CLS>Play "{movie1}"?')
    _set_raw(
        entries["MOVIE2_START"],
        f'<CHOI 2 0 1><CLS>Play "{movie2}"?' if movie2 else "Invalid Message",
    )
    for label in ("THEME_START", "OMNIBUS2_START", "OMNIBUS3_START", "OMNIBUS4_START"):
        _set_plain(entries[label], "Invalid Message")

    output_blob = build_gmd_bytes(document)
    verified = parse_gmd_bytes(output_blob)
    if any(any("\u3040" <= ch <= "\u30ff" or "\u4e00" <= ch <= "\u9fff" for ch in (e["text"] or "")) for e in verified["entries"]):
        raise ValueError(f"Japanese metadata remains in {source_path.name}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(output_blob)
    return {"entries": len(document["entries"]), "japanese_text_remaining": False}


def port_special_metadata(source_path: Path, music: dict[str, str], output_path: Path) -> dict:
    document = parse_gmd_bytes(source_path.read_bytes())
    entries = _labels(document)
    _set_plain(entries["TITLE"], "Special Issue")
    for local_index in range(1, 9):
        for field in ("TITLE", "CONTENT", "COMMENT"):
            value = music[f"BGM{local_index}_{field}"] if local_index <= 4 else "Unused"
            _set_plain(entries[f"BGM{local_index}_{field}"], value)
    composer_names = {"北川": "Kitagawa", "前馬": "Maeba", "山東": "Sando"}
    for local_index in range(1, 9):
        label = f"BGM{local_index}_COMPOSER"
        if label in entries:
            original = _visible_text(entries[label].get("text") or "").strip()
            _set_plain(entries[label], composer_names.get(original, ""))
    for local_index in range(1, 21):
        label = f"VOICE{local_index:02}_TITLE"
        value = music[f"VOICE{local_index:02}_TITLE"] if local_index <= 2 else "Unused"
        _set_plain(entries[label], value)
    _set_raw(
        entries["OMNIBUS_START"],
        '<CHOI 2 0 1><CLS>Start "Special Escapade: At the Supreme Court"?',
    )
    _set_raw(entries["MOVIE1_START"], '<CHOI 2 0 1><CLS>Play "Prototype Commentary"?')
    _set_raw(entries["MOVIE2_START"], '<CHOI 2 0 1><CLS>Play "Theme Introduction"?')
    for label in ("THEME_START", "OMNIBUS2_START", "OMNIBUS3_START", "OMNIBUS4_START"):
        _set_plain(entries[label], "Invalid Message")

    output_blob = build_gmd_bytes(document)
    verified = parse_gmd_bytes(output_blob)
    if any(JP_RE.search(entry["text"] or "") for entry in verified["entries"]):
        raise ValueError(f"Japanese metadata remains in {source_path.name}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(output_blob)
    return {"entries": len(document["entries"]), "japanese_text_remaining": False}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dlc-root", type=Path, required=True)
    parser.add_argument("--official-script-root", type=Path, required=True)
    parser.add_argument("--official-common-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    music = _text_map(args.official_common_root / "special_contents_music_eng.gmd")
    escapades = _text_map(args.official_common_root / "special_contents_e_edition_eng.gmd")
    special_candidates = list(args.dlc_root.glob("contents.*/romfs/msg/aoc00_jpn.gmd"))
    if len(special_candidates) != 1:
        raise ValueError(f"expected one special-issue metadata file, found {len(special_candidates)}")
    special_source = special_candidates[0]
    special_content = special_source.parents[2].name
    special_report = port_special_metadata(
        special_source,
        music,
        args.output_root / special_content / "romfs" / "msg" / special_source.name,
    )
    records = []
    for issue in range(1, 9):
        candidates = list(args.dlc_root.glob(f"contents.*/romfs/script/sce07_c{issue:03}_0000_jpn.gmd"))
        if len(candidates) != 1:
            raise ValueError(f"expected one 3DS source for DLC issue {issue}, found {len(candidates)}")
        source_script = candidates[0]
        content_name = source_script.parents[2].name
        destination = args.output_root / content_name / "romfs"
        script_report = port_script(
            source_script,
            args.official_script_root / f"_sce07_c{issue:03}_0000_eng.gmd",
            destination / "script" / source_script.name,
        )
        metadata_report = port_metadata(
            issue,
            source_script.parents[1] / "msg" / f"aoc{issue:02}_jpn.gmd",
            music,
            escapades,
            destination / "msg" / f"aoc{issue:02}_jpn.gmd",
        )
        records.append({"issue": issue, "content": content_name, "script": script_report, "metadata": metadata_report})

    report = {
        "official_escapades": len(records),
        "special_issue_metadata": special_report,
        "3ds_events_verified": all(r["script"]["3ds_events_verified"] for r in records),
        "files": records,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
