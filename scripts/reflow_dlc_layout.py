#!/usr/bin/env python3
"""Reflow translated DLC JSON using the final 3DS font metrics.

The Japanese container remains the authority for the maximum number of lines
available to each page.  English text uses the fewest lines it actually needs;
dialogue may expand to two lines, while UI captions and text cut-ins retain any
larger line budget present in the original resource.
"""

from __future__ import annotations

import argparse
import json
import re
import struct
from functools import lru_cache
from pathlib import Path


TAG_RE = re.compile(r"<[^<>]*>")
PAGE_RE = re.compile(r"(<PAGE>)")
E025_INTEGER_RE = re.compile(r"<E025\s+(?P<value>\d+)>")
LATIN_TYPOGRAPHY_REPLACEMENTS = {
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
}


def gfd_name_end(blob: bytes, header_size: int, float_count: int) -> int:
    offset = header_size + float_count * 4
    name_length = struct.unpack_from("<i", blob, offset)[0]
    return offset + 4 + name_length + 1


def read_3ds_advances(path: Path) -> dict[int, int]:
    blob = path.read_bytes()
    header = struct.unpack_from("<4sI8i4f", blob, 0)
    if header[0] != b"GFD\0" or header[1] != 0x00010F06:
        raise ValueError("expected a 3DS GFD v0x00010F06 font")
    count = header[7]
    offset = gfd_name_end(blob, 56, header[9])
    advances: dict[int, int] = {}
    for index in range(count):
        entry = offset + index * 20
        codepoint = struct.unpack_from("<I", blob, entry)[0]
        packed = struct.unpack_from("<I", blob, entry + 12)[0]
        advances[codepoint] = packed & 0xFFF
    return advances


def visible(value: str) -> str:
    return TAG_RE.sub("", value)


def adapt_latin_layout(value: str) -> str:
    """Use the same typography and E025 tracking mode as Scarlet English."""
    for source, target in LATIN_TYPOGRAPHY_REPLACEMENTS.items():
        value = value.replace(source, target)

    def replace_tracking(match: re.Match[str]) -> str:
        tracking = int(match.group("value"))
        if tracking == 0:
            return match.group()
        return f"<E025 {tracking}.5>"

    return E025_INTEGER_RE.sub(replace_tracking, value)


def line_width(value: str, widths: dict[int, int], fallback: int = 18) -> int:
    return sum(widths.get(ord(char), fallback) for char in value if char not in "\r\n")


def line_budget(source_segment: str) -> int:
    lines = [line for line in visible(source_segment).splitlines() if line.strip()]
    return max(2, len(lines))


def best_wrap(
    text: str, widths: dict[int, int], maximum: int, maximum_lines: int
) -> tuple[list[str] | None, int]:
    words = text.split()
    if not words:
        return [], 0
    word_widths = [line_width(word, widths) for word in words]
    space = line_width(" ", widths)

    @lru_cache(maxsize=None)
    def solve(start: int, lines_left: int) -> tuple[tuple[int, int, int], tuple[str, ...]] | None:
        if start == len(words):
            return ((0, 0, 0), ())
        if lines_left == 0:
            return None
        width = 0
        best: tuple[tuple[int, int, int], tuple[str, ...]] | None = None
        for end in range(start, len(words)):
            width += word_widths[end] + (space if end > start else 0)
            if width > maximum:
                break
            tail = solve(end + 1, lines_left - 1)
            if tail is None:
                continue
            tail_score, tail_lines = tail
            used = 1 + tail_score[0]
            ragged = (maximum - width) ** 2 + tail_score[1]
            peak = max(width, tail_score[2])
            # First use as few lines as possible.  The old ordering minimized
            # the peak width first, which split every short sentence into two
            # balanced half-lines even when it fitted on a single line.
            score = (used, ragged, peak)
            candidate = (score, (" ".join(words[start : end + 1]),) + tail_lines)
            if best is None or candidate[0] < best[0]:
                best = candidate
        return best

    result = solve(0, maximum_lines)
    if result is None:
        total = sum(word_widths) + space * (len(words) - 1)
        return None, total
    return list(result[1]), result[0][2]


def replace_first_visible_piece(segment: str, replacement: str) -> str:
    pieces = TAG_RE.split(segment)
    tags = TAG_RE.findall(segment)
    candidates = [index for index, piece in enumerate(pieces) if piece.strip()]
    if not candidates:
        return segment
    pieces[candidates[0]] = replacement
    for index in candidates[1:]:
        pieces[index] = ""
    output: list[str] = []
    for index, piece in enumerate(pieces):
        output.append(piece)
        if index < len(tags):
            output.append(tags[index])
    return "".join(output)


def reflow_document(
    source: dict, translated: dict, widths: dict[int, int], maximum: int, relative: Path
) -> tuple[dict, list[dict], int]:
    if len(source["entries"]) != len(translated["entries"]):
        raise ValueError(f"entry count mismatch: {relative}")
    overflows: list[dict] = []
    reflowed = 0
    for entry_index, (source_entry, translated_entry) in enumerate(
        zip(source["entries"], translated["entries"])
    ):
        source_parts = PAGE_RE.split(source_entry["text"])
        translated_parts = PAGE_RE.split(translated_entry["text"])
        if len(source_parts) != len(translated_parts):
            raise ValueError(f"page count mismatch: {relative}:{entry_index}")
        for part_index in range(0, len(source_parts), 2):
            translated_parts[part_index] = adapt_latin_layout(
                translated_parts[part_index]
            )
            raw = visible(translated_parts[part_index])
            text = " ".join(raw.replace("\u3000", " ").split())
            if not text:
                continue
            budget = line_budget(source_parts[part_index])
            lines, peak = best_wrap(text, widths, maximum, budget)
            if lines is None:
                overflows.append(
                    {
                        "key": f"{relative}:{entry_index}:{part_index}",
                        "line_budget": budget,
                        "total_width": peak,
                        "text": text,
                    }
                )
                continue
            replacement = "\r\n".join(lines)
            updated = replace_first_visible_piece(translated_parts[part_index], replacement)
            if updated != translated_parts[part_index]:
                translated_parts[part_index] = updated
                reflowed += 1
        translated_entry["text"] = "".join(translated_parts)
        translated_entry["text_hex"] = translated_entry["text"].encode("utf-8").hex()
    return translated, overflows, reflowed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_root", type=Path)
    parser.add_argument("translated_root", type=Path)
    parser.add_argument("font", type=Path)
    parser.add_argument("output_root", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("--maximum", type=int, default=365)
    args = parser.parse_args()

    widths = read_3ds_advances(args.font)
    all_overflows: list[dict] = []
    files = 0
    pages = 0
    for translated_path in sorted(args.translated_root.rglob("*.json")):
        relative = translated_path.relative_to(args.translated_root)
        source_path = args.source_root / relative
        if not source_path.is_file():
            raise ValueError(f"missing Japanese source: {relative}")
        source = json.loads(source_path.read_text(encoding="utf-8"))
        translated = json.loads(translated_path.read_text(encoding="utf-8"))
        translated, overflows, reflowed = reflow_document(
            source, translated, widths, args.maximum, relative
        )
        output_path = args.output_root / relative
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(translated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        all_overflows.extend(overflows)
        files += 1
        pages += reflowed

    report = {
        "files": files,
        "reflowed_pages": pages,
        "maximum_line_width": args.maximum,
        "overflow_pages": len(all_overflows),
        "overflows": all_overflows,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
