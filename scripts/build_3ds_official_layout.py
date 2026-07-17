#!/usr/bin/env python3
"""Adapt Scarlet's 3DS font advances and reflow official PC GMD lines."""

from __future__ import annotations

import argparse
import functools
import json
import math
import re
import struct
from pathlib import Path

from PIL import Image

from dgs2tool.gmd import build_gmd_bytes, parse_gmd_bytes


TAG_RE = re.compile(r"<[^>]*>")
LEADING_NEWLINES_RE = re.compile(r"^(?:\r\n|\n)+")
INTERNAL_NEWLINE_RE = re.compile(r"[ \t]*(?:\r\n|\n)[ \t]*")
WORD_INTERNAL_NEWLINE_RE = re.compile(
    r"((?:[A-Z]|<[^>]*>){16,})(?:\r\n|\n)(?=(?:[A-Z]|<[^>]*>){16,})"
)
SPECIAL_LAYOUT_TAGS = ("<CNTR>", "<SIZE ", "<RUBY>", "<RT>")
LOCATION_CAPTION_RE = re.compile(
    r"(?P<prefix><CNTR><E008><E025 7\.5><E003 10>)"
    r"(?P<date>[^<>\r\n]+)\r\n"
    r"(?P<location_prefix><CNTR><E003 5>)"
    r"(?P<location>[^<>\r\n]+)"
    r"(?P<suffix><E023>)"
)
CONCISE_LOCATION_NAMES = {
    "Supreme Court of Judicature, Defendants' Antechamber 5":
        "Supreme Court, Defendants' Antechamber 5",
    "British Supreme Court, Lord Chief Justice's Office":
        "Supreme Court, Lord Chief Justice's Office",
}


def _gfd_name_end(blob: bytes, header_size: int, float_count: int) -> int:
    offset = header_size + float_count * 4
    name_length = struct.unpack_from("<i", blob, offset)[0]
    return offset + 4 + name_length + 1


def read_pc_v3_advances(path: Path) -> dict[int, float]:
    blob = path.read_bytes()
    header = struct.unpack_from("<4sI8i7f", blob, 0)
    if header[0] != b"GFD\0" or header[1] != 0x00011107:
        raise ValueError("expected a PC GFD v0x00011107 font")
    char_count = header[7]
    offset = _gfd_name_end(blob, 56, header[9])
    advances: dict[int, float] = {}
    for index in range(char_count):
        entry = offset + index * 36
        codepoint = struct.unpack_from("<I", blob, entry)[0]
        # V3 stores glyph width/height, bearing x/y, then advance width/height.
        advance_width = struct.unpack_from("<f", blob, entry + 20)[0]
        advances[codepoint] = advance_width
    return advances


def _decode_3ds_a4_tex(path: Path) -> Image.Image:
    """Decode the square, Morton-tiled A4 font atlases used by TGAA1."""
    blob = path.read_bytes()
    if not blob.startswith(b"TEX\0") or len(blob) <= 20:
        raise ValueError("expected a 3DS MT Framework TEX font atlas")
    payload = blob[20:]
    pixel_count = len(payload) * 2
    side = math.isqrt(pixel_count)
    if side * side != pixel_count or side % 8:
        raise ValueError("expected a square 8-pixel-tiled A4 TEX atlas")

    def morton_8x8(x: int, y: int) -> int:
        return (
            ((x & 1) << 0)
            | ((y & 1) << 1)
            | ((x & 2) << 1)
            | ((y & 2) << 2)
            | ((x & 4) << 2)
            | ((y & 4) << 3)
        )

    output = bytearray(pixel_count)
    tiles_per_row = side // 8
    for y in range(side):
        for x in range(side):
            tile = (y // 8) * tiles_per_row + (x // 8)
            subpixel = morton_8x8(x & 7, y & 7)
            packed = payload[tile * 32 + subpixel // 2]
            value = (packed >> 4) if subpixel & 1 else (packed & 0xF)
            output[y * side + x] = value * 17
    return Image.frombytes("L", (side, side), bytes(output))


def read_atlas(path: Path) -> Image.Image:
    if path.read_bytes()[:4] == b"TEX\0":
        return _decode_3ds_a4_tex(path)
    return Image.open(path).convert("L")


def read_3ds_advances(path: Path) -> dict[int, int]:
    blob = path.read_bytes()
    magic, version = struct.unpack_from("<4sI", blob, 0)
    if magic != b"GFD\0":
        raise ValueError("expected a 3DS GFD font")
    if version == 0x00010F06:
        header = struct.unpack_from("<4sI8i4f", blob, 0)
        char_count = header[7]
        offset = _gfd_name_end(blob, 56, header[9])
        entry_size = 20
    elif version == 0x00010C06:
        header = struct.unpack_from("<4sI7i3f", blob, 0)
        char_count = header[7]
        offset = _gfd_name_end(blob, 48, 0)
        entry_size = 16
    else:
        raise ValueError(f"unsupported 3DS GFD version 0x{version:08X}")
    return {
        struct.unpack_from("<I", blob, offset + index * entry_size)[0]:
        struct.unpack_from("<I", blob, offset + index * entry_size + 12)[0] & 0xFFF
        for index in range(char_count)
    }


def adapt_3ds_gfd(
    source_path: Path,
    pc_advances: dict[int, float],
    atlas_path: Path,
    output_path: Path,
    scale: float,
) -> tuple[dict[int, int], dict]:
    blob = bytearray(source_path.read_bytes())
    magic, version = struct.unpack_from("<4sI", blob, 0)
    if magic != b"GFD\0":
        raise ValueError("expected a 3DS GFD font")
    if version == 0x00010F06:
        header = struct.unpack_from("<4sI8i4f", blob, 0)
        char_count = header[7]
        offset = _gfd_name_end(blob, 56, header[9])
        entry_size = 20
        dimensions = lambda tmp2: (tmp2 & 0xFFF, (tmp2 >> 12) & 0xFFF)
    elif version == 0x00010C06:
        header = struct.unpack_from("<4sI7i3f", blob, 0)
        char_count = header[7]
        offset = _gfd_name_end(blob, 48, 0)
        entry_size = 16
        dimensions = lambda tmp2: ((tmp2 >> 8) & 0xFFF, (tmp2 >> 20) & 0xFFF)
    else:
        raise ValueError(f"unsupported 3DS GFD version 0x{version:08X}")
    atlas = read_atlas(atlas_path)

    widths: dict[int, int] = {}
    changed = 0
    constrained_by_ink = 0
    for index in range(char_count):
        entry = offset + index * entry_size
        codepoint, tmp1, tmp2, tmp3 = struct.unpack_from("<4I", blob, entry)
        old_width = tmp3 & 0xFFF
        width = old_width
        if codepoint in pc_advances:
            target = math.floor(pc_advances[codepoint] * scale + 0.5)
            glyph_x = (tmp1 >> 8) & 0xFFF
            glyph_y = (tmp1 >> 20) & 0xFFF
            glyph_width, glyph_height = dimensions(tmp2)
            bbox = atlas.crop(
                (glyph_x, glyph_y, glyph_x + glyph_width, glyph_y + glyph_height)
            ).getbbox()
            ink_width = bbox[2] - bbox[0] if bbox else 0
            # Permit one pixel of normal proportional-font overhang, but never
            # let a glyph collide deeply with the following character.
            width = max(target, ink_width - 1)
            constrained_by_ink += int(width != target)
        widths[codepoint] = width
        if width != old_width:
            changed += 1
            struct.pack_into("<I", blob, entry + 12, (tmp3 & 0xFFFFF000) | width)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(blob)
    return widths, {
        "characters": char_count,
        "pc_characters": len(pc_advances),
        "changed_advances": changed,
        "ink_constrained_advances": constrained_by_ink,
        "gfd_version": f"0x{version:08X}",
        "scale": scale,
    }


def visible(text: str) -> str:
    return TAG_RE.sub("", text)


def line_width(text: str, widths: dict[int, int], fallback: int = 18) -> int:
    return sum(widths.get(ord(char), fallback) for char in visible(text) if char not in "\r\n")


def candidate_breaks(text: str) -> list[tuple[int, int]]:
    """Return (break offset, bytes to skip) at safe visible-text boundaries."""
    result: list[tuple[int, int]] = []
    in_tag = False
    for index, char in enumerate(text):
        if char == "<":
            in_tag = True
        elif char == ">":
            in_tag = False
        elif char == " " and not in_tag:
            result.append((index, 1))
    # Some official cries are intentionally a single enormous word, and one
    # Cockney stammer joins three attempts with ellipses. GMD timing tags can
    # occur inside those visible tokens, so identify boundaries on tag-free
    # text and map them back to raw offsets.
    visible_chars: list[str] = []
    raw_offsets: list[int] = []
    in_tag = False
    for index, char in enumerate(text):
        if char == "<":
            in_tag = True
        elif char == ">":
            in_tag = False
        elif not in_tag:
            visible_chars.append(char)
            raw_offsets.append(index)
    visible_text = "".join(visible_chars)
    for match in re.finditer(r"[A-Z]{16,}|\.{3}(?=[A-Za-z])", visible_text):
        indexes = (
            [match.end()]
            if match.group().startswith("...")
            else range(match.start() + 1, match.end())
        )
        result.extend((raw_offsets[index], 0) for index in indexes if index < len(raw_offsets))
    return sorted(set(result))


def reflow_segment(
    segment: str,
    widths: dict[int, int],
    maximum: int,
    max_lines: int = 3,
) -> tuple[str, dict | None]:
    leading_match = LEADING_NEWLINES_RE.match(segment)
    leading = leading_match.group() if leading_match else ""
    body = segment[len(leading) :]
    if any(tag in body for tag in SPECIAL_LAYOUT_TAGS):
        return segment, None

    original_lines = [line for line in visible(body).splitlines() if line.strip()]
    if not original_lines or len(original_lines) > max_lines:
        return segment, None
    original_widths = [line_width(line, widths) for line in original_lines]
    if max(original_widths) <= maximum:
        return segment, None

    normalized = WORD_INTERNAL_NEWLINE_RE.sub(r"\1", body)
    normalized = INTERNAL_NEWLINE_RE.sub(" ", normalized)
    opportunities = candidate_breaks(normalized)
    best: tuple[tuple[int, int, int], list[tuple[int, int]], list[int]] | None = None
    minimum_lines = max(2, len(original_lines))
    for line_count in range(minimum_lines, max_lines + 1):
        ideal = line_width(normalized, widths) / line_count

        @functools.lru_cache(maxsize=None)
        def balanced_suffix(cursor: int, remaining: int):
            if remaining == 1:
                if cursor >= len(normalized):
                    return None
                width = line_width(normalized[cursor:], widths)
                if width > maximum:
                    return None
                return ((width - ideal) ** 2, (), (width,))

            current_best = None
            for index, skip in opportunities:
                next_cursor = index + skip
                if index <= cursor or next_cursor >= len(normalized):
                    continue
                width = line_width(normalized[cursor:index], widths)
                if width > maximum:
                    continue
                suffix = balanced_suffix(next_cursor, remaining - 1)
                if suffix is None:
                    continue
                suffix_cost, suffix_breaks, suffix_widths = suffix
                candidate = (
                    (width - ideal) ** 2 + suffix_cost,
                    ((index, skip),) + suffix_breaks,
                    (width,) + suffix_widths,
                )
                if current_best is None or candidate[0] < current_best[0]:
                    current_best = candidate
            return current_best

        balanced = balanced_suffix(0, line_count)
        if balanced is not None:
            _cost, breaks, line_widths = balanced
            score = (
                line_count,
                max(line_widths),
                max(line_widths) - min(line_widths),
            )
            best = (score, list(breaks), list(line_widths))
            break

    if best is None:
        return segment, {
            "status": "overflow",
            "original_widths": original_widths,
            "total_width": line_width(normalized, widths),
            "text": visible(normalized),
        }

    _score, breaks, new_widths = best
    pieces: list[str] = []
    cursor = 0
    for index, skip in breaks:
        pieces.append(normalized[cursor:index])
        cursor = index + skip
    pieces.append(normalized[cursor:])
    replacement = "\r\n".join(pieces)
    return leading + replacement, {
        "status": "reflowed",
        "original_widths": original_widths,
        "new_widths": new_widths,
        "text": visible(replacement).replace("\r\n", " | "),
    }


def reflow_text(
    text: str,
    widths: dict[int, int],
    maximum: int,
    max_lines: int = 3,
) -> tuple[str, list[dict]]:
    segments = text.split("<PAGE>")
    reports: list[dict] = []
    output: list[str] = []
    for page_index, segment in enumerate(segments):
        replacement, report = reflow_segment(segment, widths, maximum, max_lines)
        if report is not None:
            report["page"] = page_index
            reports.append(report)
        output.append(replacement)
    result = "<PAGE>".join(output)
    if [match.group() for match in TAG_RE.finditer(result)] != [
        match.group() for match in TAG_RE.finditer(text)
    ]:
        raise ValueError("reflow changed the GMD tag sequence")
    if "".join(visible(result).split()) != "".join(visible(text).split()):
        raise ValueError("reflow changed visible wording")
    return result, reports


def reflow_location_captions(
    text: str,
    widths: dict[int, int],
    maximum: int,
) -> tuple[str, list[dict]]:
    reports: list[dict] = []

    def replace(match: re.Match[str]) -> str:
        location = match.group("location")
        original_width = line_width(location, widths)
        if original_width <= maximum:
            return match.group(0)
        replacement = CONCISE_LOCATION_NAMES.get(location)
        replacement_width = line_width(replacement, widths) if replacement else None
        if replacement is None or replacement_width > maximum:
            reports.append({
                "status": "overflow",
                "original_widths": [original_width],
                "text": location,
                "layout": "location_caption",
            })
            return match.group(0)
        report = {
            "status": "reflowed",
            "original_widths": [original_width],
            "new_widths": [replacement_width],
            "text": replacement,
            "original_text": location,
            "layout": "location_caption",
            "method": "concise_location_name",
        }
        reports.append(report)
        return (
            match.group("prefix")
            + match.group("date")
            + "\r\n"
            + match.group("location_prefix")
            + replacement
            + match.group("suffix")
        )

    return LOCATION_CAPTION_RE.sub(replace, text), reports


def reflow_tree(root: Path, widths: dict[int, int], maximum: int) -> dict:
    changed_files = 0
    reflowed = 0
    overflows: list[dict] = []
    examples: list[dict] = []
    for path in sorted(root.rglob("*.gmd")):
        document = parse_gmd_bytes(path.read_bytes())
        if re.fullmatch(r"aoc\d{2}_jpn\.gmd", path.name):
            max_lines = 6
        elif path.name == "explain_content_jpn.gmd":
            max_lines = 5
        elif path.name == "system_jpn.gmd":
            max_lines = 4
        else:
            max_lines = 3
        file_changed = False
        for entry in document["entries"]:
            text = entry.get("text")
            if text is None:
                continue
            replacement, location_reports = reflow_location_captions(text, widths, maximum)
            replacement, reports = reflow_text(replacement, widths, maximum, max_lines)
            reports = location_reports + reports
            for report in reports:
                report.update({"file": path.name, "label": entry.get("label")})
                if report["status"] == "reflowed":
                    reflowed += 1
                    if len(examples) < 30:
                        examples.append(report)
                else:
                    overflows.append(report)
            if replacement != text:
                entry["text"] = replacement
                entry["text_hex"] = ""
                file_changed = True
        if file_changed:
            rebuilt = build_gmd_bytes(document)
            verified = parse_gmd_bytes(rebuilt)
            if [entry.get("text") for entry in verified["entries"]] != [
                entry.get("text") for entry in document["entries"]
            ]:
                raise ValueError(f"GMD verification failed: {path}")
            path.write_bytes(rebuilt)
            changed_files += 1
    return {
        "maximum_line_width": maximum,
        "changed_files": changed_files,
        "reflowed_pages": reflowed,
        "overflow_pages": len(overflows),
        "overflows": overflows,
        "examples": examples,
    }


def reflow_movie_subtitles(
    path: Path,
    widths: dict[int, int],
    maximum: int,
) -> dict:
    document = parse_gmd_bytes(path.read_bytes())
    reflowed = 0
    overflows: list[dict] = []
    examples: list[dict] = []
    for entry in document["entries"]:
        text = entry.get("text")
        if text is None:
            continue
        replacement, reports = reflow_text(text, widths, maximum, max_lines=4)
        for report in reports:
            report.update({"file": path.name, "label": entry.get("label")})
            if report["status"] == "reflowed":
                reflowed += 1
                examples.append(report)
            else:
                overflows.append(report)
        if replacement != text:
            entry["text"] = replacement
            entry["text_hex"] = ""

    rebuilt = build_gmd_bytes(document)
    verified = parse_gmd_bytes(rebuilt)
    if [entry.get("text") for entry in verified["entries"]] != [
        entry.get("text") for entry in document["entries"]
    ]:
        raise ValueError(f"GMD verification failed: {path}")
    path.write_bytes(rebuilt)
    return {
        "maximum_line_width": maximum,
        "maximum_lines": 4,
        "reflowed_entries": reflowed,
        "overflow_entries": len(overflows),
        "overflows": overflows,
        "examples": examples,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pc_gfd", type=Path)
    parser.add_argument("scarlet_gfd", type=Path)
    parser.add_argument("scarlet_atlas", type=Path)
    parser.add_argument("output_gfd", type=Path)
    parser.add_argument("gmd_root", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("--scale", type=float, default=1 / 3)
    parser.add_argument("--maximum", type=int, default=365)
    parser.add_argument("--movie-subtitle-gmd", type=Path)
    parser.add_argument("--movie-maximum", type=int, default=304)
    args = parser.parse_args()

    pc_advances = read_pc_v3_advances(args.pc_gfd)
    widths, font_report = adapt_3ds_gfd(
        args.scarlet_gfd,
        pc_advances,
        args.scarlet_atlas,
        args.output_gfd,
        args.scale,
    )
    report = {
        "font": font_report,
        "reflow": reflow_tree(args.gmd_root, widths, args.maximum),
    }
    if args.movie_subtitle_gmd is not None:
        report["movie_subtitles"] = reflow_movie_subtitles(
            args.movie_subtitle_gmd,
            widths,
            args.movie_maximum,
        )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
