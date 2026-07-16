"""Batch operations for GMD trees and Luma3DS development overlays."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

from .gmd import build_gmd_bytes, parse_gmd_bytes


TITLE_ID_RE = re.compile(r"^[0-9a-fA-F]{16}$")
SCENE_RE = re.compile(r"^\d{2}$")
TAG_RE = re.compile(r"<[^>]*>")
PAGE_RE = re.compile(r"<PAGE>")
E025_INTEGER_RE = re.compile(r"<E025\s+(?P<value>\d+)>")
EVENT_BLOCK_RE = re.compile(
    r"(?P<event><E800(?:\s[^>]*)?>)(?P<gap>\s*)"
    r"(?P<command><(?P<opcode>[^/\s>]+)(?:\s[^>]*)?>)"
)

# These commands occur in the PC scripts but nowhere in the complete Japanese
# 3DS script corpus or Scarlet Study's working 3DS scripts. Event commands are
# discarded together with their PC E800 marker; inline layout commands are
# removed while keeping the official visible text untouched.
PC_ONLY_EVENT_OPCODES = {"E454", "E516", "E655", "E789", "E790", "E791"}
PC_ONLY_INLINE_OPCODES = {
    "E040",
    "E566",
    "E687",
    "E689",
    "E690",
    "E696",
    "E698",
    "E704",
    "E705",
    "E706",
    "E710",
    "ICON",
    "RGHT",
}

ICON_TAG_PATTERN = r"<ICON(?:\s[^>]*)?>"
ROTATION_CONTROLS_RE = re.compile(
    rf"<E705>{ICON_TAG_PATTERN}<E003[^>]*><E086[^>]*>"
    rf"<E696>{ICON_TAG_PATTERN}<E003[^>]*><E086[^>]*>"
    rf"<E706>{ICON_TAG_PATTERN}<E003[^>]*><E086[^>]*>"
    rf"<E704>{ICON_TAG_PATTERN}"
)
JUROR_CONTROLS_RE = re.compile(
    rf"<E698>{ICON_TAG_PATTERN}<E003[^>]*><E086[^>]*><E710>{ICON_TAG_PATTERN}"
)
TOUCH_CONTROL_RE = re.compile(rf"<E(?:687|689|690)>{ICON_TAG_PATTERN}")

# Scarlet Study's proportional 3DS font uses half-step E025 values for Latin
# text. The official PC scripts use the corresponding integer values. The PC
# font also includes U+2019, while Scarlet's GFD does not; leaving it in a GMD
# makes the renderer advance by a wide fallback glyph.
PC_TYPOGRAPHY_REPLACEMENTS = {
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _label_map(document: dict, source: Path) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for entry in document["entries"]:
        label = entry.get("label")
        if label is None:
            raise ValueError(f"unlabelled GMD entry in {source}: index {entry['index']}")
        if label in result:
            raise ValueError(f"duplicate GMD label in {source}: {label}")
        result[label] = entry
    return result


def _segments(text: str) -> list[str]:
    result: list[str] = []
    start = 0
    for match in PAGE_RE.finditer(text):
        result.append(text[start : match.end()])
        start = match.end()
    result.append(text[start:])
    return result


def _visible_text(text: str) -> str:
    return TAG_RE.sub("", text)


def _select_localized_official_segments(
    reference_segments: list[str], official_segments: list[str]
) -> tuple[list[str], int]:
    """Collapse PC-only honorific/title alternatives to the localized variant.

    Chronicles carries adjacent alternatives such as ``Susato-san`` and
    ``Miss Susato`` behind a PC-only condition. The original 3DS script has a
    single page, so select the fully localized ``Miss``/``Mr`` alternative.
    """
    if len(reference_segments) == len(official_segments):
        return official_segments, 0
    if len(official_segments) < len(reference_segments):
        return official_segments, 0

    excess = len(official_segments) - len(reference_segments)
    removable: list[int] = []
    reference_visible_pages = sum(bool(_visible_text(segment).strip()) for segment in reference_segments)
    for index in range(len(official_segments) - 1):
        current = _visible_text(official_segments[index])
        following = _visible_text(official_segments[index + 1])
        current_words = " ".join(current.split())
        following_words = " ".join(following.split())
        if "-san" in current and ("Miss " in following or "Mr " in following):
            removable.append(index)
        elif "when Iris would visit" in current_words and "when you would visit" in following_words:
            # The same examination entry is used both while Iris is absent and
            # while she is standing beside the speaker. The latter has extra
            # response pages in the original 3DS entry.
            removable.append(index if reference_visible_pages > 4 else index + 1)
    if len(removable) < excess:
        return official_segments, 0
    removed = set(removable[:excess])
    return [segment for index, segment in enumerate(official_segments) if index not in removed], excess


def _text_body_offset(segment: str) -> int | None:
    """Return the offset after the 3DS/PC event that opens visible text."""
    visible_offset: int | None = None
    cursor = 0
    for match in TAG_RE.finditer(segment):
        visible = re.search(r"\S", segment[cursor : match.start()])
        if visible:
            visible_offset = cursor + visible.start()
            break
        cursor = match.end()
    if visible_offset is None:
        visible = re.search(r"\S", segment[cursor:])
        if visible:
            visible_offset = cursor + visible.start()
    if visible_offset is None:
        return None

    tags = list(TAG_RE.finditer(segment, 0, visible_offset))
    event_index = next(
        (index for index in range(len(tags) - 1, -1, -1) if tags[index].group().startswith("<E800 ")),
        None,
    )
    if event_index is None or event_index + 1 >= len(tags):
        return None
    return tags[event_index + 1].end()


def _strip_pc_only_commands(text: str) -> tuple[str, Counter[str]]:
    removed: Counter[str] = Counter()

    def event_replacement(match: re.Match[str]) -> str:
        opcode = match.group("opcode").upper()
        if opcode not in PC_ONLY_EVENT_OPCODES:
            return match.group()
        removed[opcode] += 1
        return match.group("gap")

    text = EVENT_BLOCK_RE.sub(event_replacement, text)

    def inline_replacement(match: re.Match[str]) -> str:
        raw = match.group()
        opcode = raw[1:-1].split(None, 1)[0].upper()
        if opcode not in PC_ONLY_INLINE_OPCODES:
            return raw
        removed[opcode] += 1
        return ""

    return TAG_RE.sub(inline_replacement, text), removed


def _adapt_pc_control_icons(text: str) -> tuple[str, Counter[str]]:
    """Replace PC-only control glyph groups with grammatical 3DS wording."""
    adapted: Counter[str] = Counter()

    def replace_rotation(_match: re.Match[str]) -> str:
        adapted["touch-screen dials"] += 1
        return "the touch-screen dials"

    def replace_juror(_match: re.Match[str]) -> str:
        adapted["juror touch screen"] += 1
        return "the touch screen"

    def replace_touch(_match: re.Match[str]) -> str:
        adapted["touch screen"] += 1
        return "the touch screen"

    text = ROTATION_CONTROLS_RE.sub(replace_rotation, text)
    text = JUROR_CONTROLS_RE.sub(replace_juror, text)
    text = TOUCH_CONTROL_RE.sub(replace_touch, text)
    return text, adapted


def _adapt_pc_text_layout(text: str) -> tuple[str, Counter[str]]:
    """Adapt PC typography and Latin-font tracking to Scarlet's renderer."""
    adapted: Counter[str] = Counter()

    for source, target in PC_TYPOGRAPHY_REPLACEMENTS.items():
        count = text.count(source)
        if count:
            text = text.replace(source, target)
            adapted[f"typography U+{ord(source):04X}"] += count

    def replace_tracking(match: re.Match[str]) -> str:
        value = int(match.group("value"))
        if value == 0:
            return match.group()
        adapted["E025 Latin half-step"] += 1
        return f"<E025 {value}.5>"

    return E025_INTEGER_RE.sub(replace_tracking, text), adapted


def _event_blocks(text: str) -> list[re.Match[str]]:
    return list(EVENT_BLOCK_RE.finditer(text))


def _restore_3ds_event_blocks(official: str, japanese: str) -> str:
    """Keep PC prose/inline timing but restore every E800-linked 3DS event."""
    official_blocks = _event_blocks(official)
    japanese_blocks = _event_blocks(japanese)
    official_opcodes = [match.group("opcode").upper() for match in official_blocks]
    japanese_opcodes = [match.group("opcode").upper() for match in japanese_blocks]
    matcher = SequenceMatcher(None, official_opcodes, japanese_opcodes, autojunk=False)

    prefixes: dict[int, list[str]] = {}
    replacements: dict[int, str] = {}
    for operation, first_start, first_end, second_start, second_end in matcher.get_opcodes():
        if operation == "equal":
            for first_index, second_index in zip(
                range(first_start, first_end), range(second_start, second_end)
            ):
                replacements[first_index] = japanese_blocks[second_index].group()
        elif operation == "delete":
            for first_index in range(first_start, first_end):
                replacements[first_index] = ""
        elif operation == "insert":
            prefixes.setdefault(first_start, []).extend(
                match.group() for match in japanese_blocks[second_start:second_end]
            )
        elif operation == "replace":
            prefixes.setdefault(first_start, []).extend(
                match.group() for match in japanese_blocks[second_start:second_end]
            )
            for first_index in range(first_start, first_end):
                replacements[first_index] = ""

    output: list[str] = []
    cursor = 0
    for index, block in enumerate(official_blocks):
        output.append(official[cursor : block.start()])
        output.extend(prefixes.get(index, []))
        output.append(replacements.get(index, block.group()))
        cursor = block.end()
    output.append(official[cursor:])
    output.extend(prefixes.get(len(official_blocks), []))
    return "".join(output)


def _official_segments_text(candidate: str, official: str) -> str:
    official, _adapted = _adapt_pc_control_icons(official)
    official, _layout_adapted = _adapt_pc_text_layout(official)
    candidate_segments = _segments(candidate)
    official_segments = _segments(official)
    official_segments, _ = _select_localized_official_segments(
        candidate_segments, official_segments
    )
    if len(candidate_segments) != len(official_segments):
        raise ValueError("page count changed during official text transfer")
    result: list[str] = []
    for candidate_segment, official_segment in zip(candidate_segments, official_segments):
        if not _visible_text(official_segment).strip():
            continue
        candidate_offset = _text_body_offset(candidate_segment)
        if candidate_offset is None:
            raise ValueError("candidate lost its text-opening event")
        result.append(_visible_text(candidate_segment[candidate_offset:]))
    return "".join(result)


def _selected_official_text(reference: str, official: str) -> str:
    official, _adapted = _adapt_pc_control_icons(official)
    official, _layout_adapted = _adapt_pc_text_layout(official)
    reference_segments = _segments(reference)
    official_segments, _ = _select_localized_official_segments(
        reference_segments, _segments(official)
    )
    if len(reference_segments) != len(official_segments):
        raise ValueError("official page count does not fit the 3DS entry")
    result: list[str] = []
    for segment in official_segments:
        if not _visible_text(segment).strip():
            continue
        offset = _text_body_offset(segment)
        if offset is None:
            raise ValueError("official segment has no text-opening event")
        result.append(_visible_text(segment[offset:]))
    return "".join(result)


def _merge_official_text(japanese: str, official: str) -> tuple[str, dict]:
    official, control_adaptations = _adapt_pc_control_icons(official)
    official, layout_adaptations = _adapt_pc_text_layout(official)
    japanese_segments = _segments(japanese)
    official_segments = _segments(official)
    official_segments, selected_variant_pages = _select_localized_official_segments(
        japanese_segments, official_segments
    )
    if len(japanese_segments) != len(official_segments):
        raise ValueError(
            f"page count differs: 3DS={len(japanese_segments) - 1}, PC={len(official_segments) - 1}"
        )

    output: list[str] = []
    removed: Counter[str] = Counter()
    text_segments = 0
    structural_literal_segments = 0
    for index, (japanese_segment, official_segment) in enumerate(
        zip(japanese_segments, official_segments)
    ):
        japanese_has_text = bool(_visible_text(japanese_segment).strip())
        official_has_text = bool(_visible_text(official_segment).strip())
        if not official_has_text:
            output.append(japanese_segment)
            structural_literal_segments += int(japanese_has_text)
            continue
        if not japanese_has_text:
            raise ValueError(f"official text has no Japanese 3DS segment at page {index}")

        japanese_offset = _text_body_offset(japanese_segment)
        official_offset = _text_body_offset(official_segment)
        if japanese_offset is None or official_offset is None:
            raise ValueError(f"could not locate text-opening event at page {index}")

        official_body, body_removed = _strip_pc_only_commands(official_segment[official_offset:])
        removed.update(body_removed)
        merged_body = _restore_3ds_event_blocks(
            official_body,
            japanese_segment[japanese_offset:],
        )
        candidate_segment = japanese_segment[:japanese_offset] + merged_body
        if [match.group() for match in _event_blocks(candidate_segment)] != [
            match.group() for match in _event_blocks(japanese_segment)
        ]:
            raise ValueError(f"3DS event block verification failed at page {index}")
        output.append(candidate_segment)
        text_segments += 1

    merged = "".join(output)
    if _official_segments_text(merged, official) != _selected_official_text(merged, official):
        raise ValueError("visible official text changed during 3DS event restoration")
    return merged, {
        "text_segments": text_segments,
        "structural_literal_segments": structural_literal_segments,
        "selected_localized_variant_pages": selected_variant_pages,
        "removed_pc_commands": dict(sorted(removed.items())),
        "3ds_control_adaptations": dict(sorted(control_adaptations.items())),
        "3ds_layout_adaptations": dict(sorted(layout_adaptations.items())),
    }


def port_official_gmd_tree(
    japanese_root: Path,
    english_root: Path,
    output_root: Path,
    scenes: tuple[str, ...] = ("00", "01", "02", "03", "04"),
    include_macros: bool = True,
) -> dict:
    """Port official PC English strings into Japanese 3DS GMD containers.

    Matching is deliberately strict: filenames are paired by their language
    suffix and entries are paired only by unique GMD labels.  The Japanese
    document supplies all container metadata and E800-linked event blocks.
    Official text and inline timing are transferred page by page, while known
    PC-only commands are omitted. Files without a complete official match are
    reported and omitted from the overlay.
    """
    normalized_scenes = tuple(dict.fromkeys(str(scene).zfill(2) for scene in scenes))
    invalid_scenes = [scene for scene in normalized_scenes if not SCENE_RE.fullmatch(scene)]
    if invalid_scenes:
        raise ValueError(f"scene IDs must contain exactly two digits: {', '.join(invalid_scenes)}")

    japanese_root = japanese_root.resolve()
    english_root = english_root.resolve()
    if not japanese_root.is_dir():
        raise ValueError(f"Japanese GMD directory does not exist: {japanese_root}")
    if not english_root.is_dir():
        raise ValueError(f"English GMD directory does not exist: {english_root}")

    destination_root = output_root / "romfs" / "script" / "_output"
    selected = sorted(
        path
        for path in japanese_root.rglob("*.gmd")
        if path.is_file()
        and (
            any(path.name.startswith(f"_sce{scene}") for scene in normalized_scenes)
            or (include_macros and path.name.startswith("_macro"))
        )
    )
    records: list[dict] = []
    written_entries = 0
    written_text_segments = 0
    selected_localized_variant_pages = 0
    removed_pc_commands: Counter[str] = Counter()
    control_adaptations: Counter[str] = Counter()
    layout_adaptations: Counter[str] = Counter()

    for japanese_path in selected:
        relative = japanese_path.relative_to(japanese_root)
        if japanese_path.name.endswith("_jpn.gmd"):
            english_name = japanese_path.name[: -len("_jpn.gmd")] + "_eng.gmd"
        else:
            records.append(
                {
                    "japanese": relative.as_posix(),
                    "status": "unsupported_filename",
                    "written": False,
                }
            )
            continue

        english_path = english_root / relative.parent / english_name
        if not english_path.is_file():
            records.append(
                {
                    "japanese": relative.as_posix(),
                    "english": english_path.relative_to(english_root).as_posix(),
                    "status": "missing_official_english",
                    "written": False,
                }
            )
            continue

        japanese_blob = japanese_path.read_bytes()
        english_blob = english_path.read_bytes()
        japanese = parse_gmd_bytes(japanese_blob)
        english = parse_gmd_bytes(english_blob)
        japanese_by_label = _label_map(japanese, japanese_path)
        english_by_label = _label_map(english, english_path)
        missing_labels = sorted(set(japanese_by_label) - set(english_by_label))
        extra_labels = sorted(set(english_by_label) - set(japanese_by_label))
        if missing_labels:
            records.append(
                {
                    "japanese": relative.as_posix(),
                    "english": english_path.relative_to(english_root).as_posix(),
                    "status": "missing_official_labels",
                    "written": False,
                    "missing_labels": missing_labels,
                    "extra_official_labels": extra_labels,
                }
            )
            continue

        ported = copy.deepcopy(japanese)
        file_text_segments = 0
        file_selected_variant_pages = 0
        file_removed_pc_commands: Counter[str] = Counter()
        file_control_adaptations: Counter[str] = Counter()
        file_layout_adaptations: Counter[str] = Counter()
        try:
            for entry in ported["entries"]:
                official = english_by_label[entry["label"]]
                if entry.get("text") is None or official.get("text") is None:
                    raise ValueError(f"non-UTF-8 entry: {entry['label']}")
                entry["text"], merge_report = _merge_official_text(
                    entry["text"], official["text"]
                )
                entry["text_hex"] = ""
                file_text_segments += merge_report["text_segments"]
                file_selected_variant_pages += merge_report["selected_localized_variant_pages"]
                file_removed_pc_commands.update(merge_report["removed_pc_commands"])
                file_control_adaptations.update(merge_report["3ds_control_adaptations"])
                file_layout_adaptations.update(merge_report["3ds_layout_adaptations"])
        except ValueError as error:
            records.append(
                {
                    "japanese": relative.as_posix(),
                    "english": english_path.relative_to(english_root).as_posix(),
                    "status": "incompatible_text_structure",
                    "written": False,
                    "error": str(error),
                }
            )
            continue

        output_blob = build_gmd_bytes(ported)
        verified = parse_gmd_bytes(output_blob)
        verified_by_label = _label_map(verified, destination_root / relative)
        for label, entry in verified_by_label.items():
            official = english_by_label[label]
            source_3ds = japanese_by_label[label]
            if _official_segments_text(entry["text"], official["text"]) != _selected_official_text(
                entry["text"], official["text"]
            ):
                raise ValueError(f"official text verification failed for {relative}: {label}")
            if [match.group() for match in _event_blocks(entry["text"])] != [
                match.group() for match in _event_blocks(source_3ds["text"])
            ]:
                raise ValueError(f"3DS event verification failed for {relative}: {label}")

        destination = destination_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(output_blob)
        written_entries += len(ported["entries"])
        written_text_segments += file_text_segments
        selected_localized_variant_pages += file_selected_variant_pages
        removed_pc_commands.update(file_removed_pc_commands)
        control_adaptations.update(file_control_adaptations)
        layout_adaptations.update(file_layout_adaptations)
        records.append(
            {
                "japanese": relative.as_posix(),
                "english": english_path.relative_to(english_root).as_posix(),
                "output": destination.relative_to(output_root).as_posix(),
                "status": "official_superset" if extra_labels else "exact_labels",
                "written": True,
                "entries": len(ported["entries"]),
                "text_segments": file_text_segments,
                "selected_localized_variant_pages": file_selected_variant_pages,
                "extra_official_labels": extra_labels,
                "removed_pc_commands": dict(sorted(file_removed_pc_commands.items())),
                "3ds_control_adaptations": dict(sorted(file_control_adaptations.items())),
                "3ds_layout_adaptations": dict(sorted(file_layout_adaptations.items())),
                "sha256": {
                    "japanese_container": _sha256(japanese_blob),
                    "official_english": _sha256(english_blob),
                    "output_3ds": _sha256(output_blob),
                },
            }
        )

    counts = {
        status: sum(record["status"] == status for record in records)
        for status in (
            "exact_labels",
            "official_superset",
            "missing_official_english",
            "missing_official_labels",
            "incompatible_text_structure",
            "unsupported_filename",
        )
    }
    return {
        "japanese_root": str(japanese_root),
        "english_root": str(english_root),
        "destination": str(destination_root),
        "scenes": list(normalized_scenes),
        "include_macros": include_macros,
        "selected_files": len(selected),
        "written_files": sum(record["written"] for record in records),
        "written_entries": written_entries,
        "written_text_segments": written_text_segments,
        "selected_localized_variant_pages": selected_localized_variant_pages,
        "removed_pc_commands": dict(sorted(removed_pc_commands.items())),
        "3ds_control_adaptations": dict(sorted(control_adaptations.items())),
        "3ds_layout_adaptations": dict(sorted(layout_adaptations.items())),
        "official_text_integrity_verified": True,
        "3ds_event_blocks_verified": True,
        "counts": counts,
        "files": records,
    }


def port_official_message_tree(
    japanese_root: Path,
    english_root: Path,
    output_root: Path,
) -> dict:
    """Port non-script GMD messages while preserving 3DS containers.

    Message tables normally use identical labels. A few retail files label
    only their first entry on 3DS, so equal-length tables fall back to index
    matching and report that choice explicitly.
    """
    japanese_root = japanese_root.resolve()
    english_root = english_root.resolve()
    destination_root = output_root / "romfs" / "msg"
    if not japanese_root.is_dir() or not english_root.is_dir():
        raise ValueError("Japanese and English message roots must be directories")

    records: list[dict] = []
    layout_adaptations: Counter[str] = Counter()
    for japanese_path in sorted(japanese_root.rglob("*_jpn.gmd")):
        relative = japanese_path.relative_to(japanese_root)
        english_name = japanese_path.name[: -len("_jpn.gmd")] + "_eng.gmd"
        english_path = english_root / relative.parent / english_name
        if not english_path.is_file():
            records.append(
                {
                    "japanese": relative.as_posix(),
                    "english": english_path.relative_to(english_root).as_posix(),
                    "status": "missing_official_english",
                    "written": False,
                }
            )
            continue

        japanese_blob = japanese_path.read_bytes()
        english_blob = english_path.read_bytes()
        japanese = parse_gmd_bytes(japanese_blob)
        english = parse_gmd_bytes(english_blob)
        named_japanese = [entry.get("label") for entry in japanese["entries"]]
        named_english = [entry.get("label") for entry in english["entries"]]

        japanese_by_label = {
            entry["label"]: entry for entry in japanese["entries"] if entry.get("label") is not None
        }
        english_by_label = {
            entry["label"]: entry for entry in english["entries"] if entry.get("label") is not None
        }

        if all(label is not None for label in named_japanese) and set(named_japanese) <= set(named_english):
            english_by_label = {entry["label"]: entry for entry in english["entries"]}
            transfer_pairs = [
                (index, english_by_label[entry["label"]])
                for index, entry in enumerate(japanese["entries"])
            ]
            match_mode = "label"
        elif len(japanese["entries"]) == len(english["entries"]):
            transfer_pairs = list(enumerate(english["entries"]))
            match_mode = "index"
        elif set(japanese_by_label) & set(english_by_label):
            transfer_pairs = [
                (index, english_by_label[entry["label"]])
                for index, entry in enumerate(japanese["entries"])
                if entry.get("label") in english_by_label
            ]
            match_mode = "partial_label"
        else:
            records.append(
                {
                    "japanese": relative.as_posix(),
                    "english": english_path.relative_to(english_root).as_posix(),
                    "status": "incompatible_entries",
                    "written": False,
                    "japanese_entries": len(japanese["entries"]),
                    "official_entries": len(english["entries"]),
                }
            )
            continue

        ported = copy.deepcopy(japanese)
        file_layout_adaptations: Counter[str] = Counter()
        expected_text: dict[int, str | None] = {}
        for index, official in transfer_pairs:
            target = ported["entries"][index]
            official_text = official.get("text")
            if official_text is not None:
                official_text, adapted = _adapt_pc_text_layout(official_text)
                file_layout_adaptations.update(adapted)
            target["text"] = official_text
            target["text_hex"] = ""
            expected_text[index] = official_text
        output_blob = build_gmd_bytes(ported)
        verified = parse_gmd_bytes(output_blob)
        transferred_indexes = {index for index, _official in transfer_pairs}
        for index, _official in transfer_pairs:
            if verified["entries"][index].get("text") != expected_text[index]:
                raise ValueError(f"official message verification failed for {relative}: index {index}")
        for index, original in enumerate(japanese["entries"]):
            if index not in transferred_indexes and verified["entries"][index].get("text") != original.get("text"):
                raise ValueError(f"preserved message verification failed for {relative}: index {index}")

        destination = destination_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(output_blob)
        layout_adaptations.update(file_layout_adaptations)
        records.append(
            {
                "japanese": relative.as_posix(),
                "english": english_path.relative_to(english_root).as_posix(),
                "output": destination.relative_to(output_root).as_posix(),
                "status": "ported",
                "written": True,
                "match_mode": match_mode,
                "entries": len(transfer_pairs),
                "target_entries": len(ported["entries"]),
                "preserved_entries": len(ported["entries"]) - len(transfer_pairs),
                "3ds_layout_adaptations": dict(sorted(file_layout_adaptations.items())),
                "sha256": {
                    "japanese_container": _sha256(japanese_blob),
                    "official_english": _sha256(english_blob),
                    "output_3ds": _sha256(output_blob),
                },
            }
        )

    return {
        "japanese_root": str(japanese_root),
        "english_root": str(english_root),
        "destination": str(destination_root),
        "selected_files": len(records),
        "written_files": sum(record["written"] for record in records),
        "written_entries": sum(record.get("entries", 0) for record in records),
        "3ds_layout_adaptations": dict(sorted(layout_adaptations.items())),
        "counts": {
            status: sum(record["status"] == status for record in records)
            for status in ("ported", "missing_official_english", "incompatible_entries")
        },
        "official_text_integrity_verified": True,
        "files": records,
    }


def dump_gmd_tree(root: Path, output: Path) -> dict:
    root = root.resolve()
    files = sorted(path for path in root.rglob("*.gmd") if path.is_file())
    exported: list[dict] = []

    for source in files:
        relative = source.relative_to(root)
        destination = output / relative.with_suffix(relative.suffix + ".json")
        document = parse_gmd_bytes(source.read_bytes())
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        exported.append(
            {
                "source": relative.as_posix(),
                "output": destination.relative_to(output).as_posix(),
                "entries": len(document["entries"]),
                "version": document["metadata"]["version"],
            }
        )

    return {"root": str(root), "count": len(exported), "files": exported}


def stage_layeredfs(source_root: Path, sd_root: Path, title_id: str = "00040000001AE200") -> dict:
    if not TITLE_ID_RE.fullmatch(title_id):
        raise ValueError("3DS title ID must be exactly 16 hexadecimal characters")

    source_root = source_root.resolve()
    romfs_root = source_root / "romfs" if (source_root / "romfs").is_dir() else source_root
    if not romfs_root.is_dir():
        raise ValueError(f"source RomFS tree does not exist: {romfs_root}")

    destination_root = sd_root / "luma" / "titles" / title_id.upper() / "romfs"
    copied: list[dict] = []
    for source in sorted(path for path in romfs_root.rglob("*") if path.is_file()):
        relative = source.relative_to(romfs_root)
        destination = destination_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied.append({"path": relative.as_posix(), "size": source.stat().st_size})

    return {
        "title_id": title_id.upper(),
        "destination": str(destination_root),
        "file_count": len(copied),
        "total_size": sum(item["size"] for item in copied),
        "files": copied,
    }
