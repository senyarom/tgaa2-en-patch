#!/usr/bin/env python3
"""Adapt Scarlet's 3DS font advances and reflow official PC GMD lines."""

from __future__ import annotations

import argparse
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
SPECIAL_LAYOUT_TAGS = ("<CNTR>", "<SIZE ", "<RUBY>", "<RT>")


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


def adapt_3ds_gfd(
    source_path: Path,
    pc_advances: dict[int, float],
    atlas_path: Path,
    output_path: Path,
    scale: float,
) -> tuple[dict[int, int], dict]:
    blob = bytearray(source_path.read_bytes())
    header = struct.unpack_from("<4sI8i4f", blob, 0)
    if header[0] != b"GFD\0" or header[1] != 0x00010F06:
        raise ValueError("expected a 3DS GFD v0x00010F06 font")
    char_count = header[7]
    offset = _gfd_name_end(blob, 56, header[9])
    atlas = Image.open(atlas_path).convert("L")

    widths: dict[int, int] = {}
    changed = 0
    constrained_by_ink = 0
    for index in range(char_count):
        entry = offset + index * 20
        codepoint, tmp1, tmp2, tmp3, _pos_x, _pos_y, _end = struct.unpack_from(
            "<4I2BH", blob, entry
        )
        old_width = tmp3 & 0xFFF
        width = old_width
        if codepoint in pc_advances:
            target = math.floor(pc_advances[codepoint] * scale + 0.5)
            glyph_x = (tmp1 >> 8) & 0xFFF
            glyph_y = (tmp1 >> 20) & 0xFFF
            glyph_width = tmp2 & 0xFFF
            glyph_height = (tmp2 >> 12) & 0xFFF
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
        "scale": scale,
    }


def visible(text: str) -> str:
    return TAG_RE.sub("", text)


def line_width(text: str, widths: dict[int, int], fallback: int = 18) -> int:
    return sum(widths.get(ord(char), fallback) for char in visible(text) if char not in "\r\n")


def candidate_spaces(text: str) -> list[int]:
    result: list[int] = []
    in_tag = False
    for index, char in enumerate(text):
        if char == "<":
            in_tag = True
        elif char == ">":
            in_tag = False
        elif char == " " and not in_tag:
            result.append(index)
    return result


def reflow_segment(segment: str, widths: dict[int, int], maximum: int) -> tuple[str, dict | None]:
    leading_match = LEADING_NEWLINES_RE.match(segment)
    leading = leading_match.group() if leading_match else ""
    body = segment[len(leading) :]
    if any(tag in body for tag in SPECIAL_LAYOUT_TAGS):
        return segment, None

    original_lines = [line for line in visible(body).splitlines() if line.strip()]
    if not original_lines or len(original_lines) > 2:
        return segment, None
    original_widths = [line_width(line, widths) for line in original_lines]
    if max(original_widths) <= maximum:
        return segment, None

    normalized = INTERNAL_NEWLINE_RE.sub(" ", body)
    best: tuple[int, int, int, int, str] | None = None
    for index in candidate_spaces(normalized):
        left = normalized[:index]
        right = normalized[index + 1 :]
        left_width = line_width(left, widths)
        right_width = line_width(right, widths)
        if left_width > maximum or right_width > maximum:
            continue
        score = (max(left_width, right_width), abs(left_width - right_width))
        candidate = (score[0], score[1], left_width, right_width, left + "\r\n" + right)
        if best is None or candidate[:2] < best[:2]:
            best = candidate

    if best is None:
        return segment, {
            "status": "overflow",
            "original_widths": original_widths,
            "total_width": line_width(normalized, widths),
            "text": visible(normalized),
        }

    return leading + best[4], {
        "status": "reflowed",
        "original_widths": original_widths,
        "new_widths": [best[2], best[3]],
        "text": visible(best[4]).replace("\r\n", " | "),
    }


def reflow_text(text: str, widths: dict[int, int], maximum: int) -> tuple[str, list[dict]]:
    segments = text.split("<PAGE>")
    reports: list[dict] = []
    output: list[str] = []
    for page_index, segment in enumerate(segments):
        replacement, report = reflow_segment(segment, widths, maximum)
        if report is not None:
            report["page"] = page_index
            reports.append(report)
        output.append(replacement)
    result = "<PAGE>".join(output)
    if [match.group() for match in TAG_RE.finditer(result)] != [
        match.group() for match in TAG_RE.finditer(text)
    ]:
        raise ValueError("reflow changed the GMD tag sequence")
    if " ".join(visible(result).split()) != " ".join(visible(text).split()):
        raise ValueError("reflow changed visible wording")
    return result, reports


def reflow_tree(root: Path, widths: dict[int, int], maximum: int) -> dict:
    changed_files = 0
    reflowed = 0
    overflows: list[dict] = []
    examples: list[dict] = []
    for path in sorted(root.rglob("*.gmd")):
        document = parse_gmd_bytes(path.read_bytes())
        file_changed = False
        for entry in document["entries"]:
            text = entry.get("text")
            if text is None:
                continue
            replacement, reports = reflow_text(text, widths, maximum)
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
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
