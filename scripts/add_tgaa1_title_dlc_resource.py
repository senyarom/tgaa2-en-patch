#!/usr/bin/env python3
"""Give TGAA1's DLC label an isolated title-menu texture resource."""

from __future__ import annotations

import argparse
import struct
from dataclasses import replace
from pathlib import Path

from dgs2tool.arc import ArcEntry, build_arc_bytes, parse_arc


GUI_ENTRY = "UI/4_menu/40_title/title_top.gui"
PANEL_ENTRY = "UI/4_menu/40_title/tex/title_panel_BM_NOMIP.tex"
DLC_RESOURCE = "UI\\4_menu\\40_title\\tex\\title_dlc_BM_NOMIP"
DLC_ENTRY = DLC_RESOURCE.replace("\\", "/") + ".tex"
DLC_NAME = "title_dlc"

POINTER_FIELDS = (
    0xEC,
    0xF0,
    0xF4,
    0xF8,
    0xFC,
    0x104,
    0x108,
    0x10C,
    0x110,
    0x114,
    0x118,
    0x120,
)


def u32(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def set_u32(data: bytearray, offset: int, value: int) -> None:
    struct.pack_into("<I", data, offset, value)


def cstring(data: bytes | bytearray, offset: int) -> str:
    end = data.find(b"\0", offset)
    if end < 0:
        raise ValueError("unterminated GUI string")
    return bytes(data[offset:end]).decode("ascii")


def shift_header_pointers(data: bytearray, threshold: int, amount: int) -> None:
    for field in POINTER_FIELDS:
        value = u32(data, field)
        if value >= threshold:
            set_u32(data, field, value + amount)


def property_layout(data: bytes | bytearray) -> tuple[int, int]:
    start = u32(data, 0xB4)
    end = u32(data, 0xB8)
    count = u32(data, 0x38)
    span = end - start
    if span != count * 0x10:
        raise ValueError("expected 16-byte TGAA1 GUI properties")
    return start, 0x10


def patch_panel_text_texture(data: bytearray, resource_value: int) -> None:
    string_pool = u32(data, 0x104)
    node_count = u32(data, 0x30)
    node_start = 0x2D0
    node_size = 0x24
    nodes: list[tuple[str, int]] = []
    for index in range(node_count):
        offset = node_start + index * node_size
        name = cstring(data, string_pool + u32(data, offset + 20))
        nodes.append((name, u32(data, offset + 28)))

    target_index = next(
        index for index, (name, _start) in enumerate(nodes) if name == "panel_text_02"
    )
    first_property = nodes[target_index][1]
    last_property = nodes[target_index + 1][1]
    property_pool, property_size = property_layout(data)
    for index in range(first_property, last_property):
        offset = property_pool + index * property_size
        name = cstring(data, string_pool + u32(data, offset + 8))
        if name == "Texture":
            if u32(data, offset) & 0xFF != 7:
                raise ValueError("panel_text_02 Texture has an unexpected type")
            set_u32(data, offset + 12, resource_value)
            return
    raise ValueError("panel_text_02 Texture property was not found")


def add_dlc_resource(gui: bytes) -> bytes:
    if gui[:4] != b"GUI\0" or u32(gui, 8) != len(gui):
        raise ValueError("invalid TGAA1 title GUI")

    output = bytearray(gui)
    resource_count = u32(output, 0x70)
    resource_table = u32(output, 0xC8)
    resource_size = 0x30
    resource_end = resource_table + resource_count * resource_size
    if resource_count != 2 or resource_end != u32(output, 0x108):
        raise ValueError("unexpected title GUI texture-resource layout")

    string_pool = u32(output, 0x104)
    string_end = u32(output, 0x120)
    path = DLC_RESOURCE.encode("ascii") + b"\0"
    name = DLC_NAME.encode("ascii") + b"\0"
    strings = path + name
    strings += b"\0" * ((-len(strings)) & 0xF)
    path_offset = string_end - string_pool
    name_offset = path_offset + len(path)

    descriptor = bytearray(output[resource_table : resource_table + resource_size])
    set_u32(descriptor, 0, resource_count + 1)
    set_u32(descriptor, 24, path_offset)
    set_u32(descriptor, 28, name_offset)

    output[resource_end:resource_end] = descriptor
    shift_header_pointers(output, resource_end, resource_size)
    shifted_string_end = string_end + resource_size
    output[shifted_string_end:shifted_string_end] = strings
    shift_header_pointers(output, shifted_string_end, len(strings))

    set_u32(output, 0x70, resource_count + 1)
    # In-memory texture references are 0x14 bytes each: the existing panel
    # and character resources use 0x20 and 0x34, so the appended one is 0x48.
    patch_panel_text_texture(output, 0x20 + resource_count * 0x14)
    set_u32(output, 8, len(output))
    return bytes(output)


def new_texture_entry(template: ArcEntry, data: bytes, index: int) -> ArcEntry:
    raw_base = DLC_ENTRY.removesuffix(".tex").encode("ascii")
    if len(raw_base) >= len(template.raw_name):
        raise ValueError("DLC texture path is too long for the ARC table")
    raw_name = raw_base + b"\0" * (len(template.raw_name) - len(raw_base))
    return replace(
        template,
        index=index,
        name=DLC_ENTRY,
        compressed_size=0,
        decompressed_size=len(data),
        offset=0,
        data=data,
        stored_data=b"",
        raw_name=raw_name,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_arc", type=Path)
    parser.add_argument("patched_gui", type=Path)
    parser.add_argument("dlc_texture", type=Path)
    parser.add_argument("output_arc", type=Path)
    args = parser.parse_args()

    archive = parse_arc(args.input_arc.read_bytes())
    entries: list[ArcEntry] = archive["entries"]
    if any(entry.name == DLC_ENTRY for entry in entries):
        raise ValueError("ARC already contains the DLC texture resource")
    panel_index = next(
        index for index, entry in enumerate(entries) if entry.name == PANEL_ENTRY
    )
    panel = entries[panel_index]
    gui = add_dlc_resource(args.patched_gui.read_bytes())
    texture = args.dlc_texture.read_bytes()
    # Title ARC dependencies precede the GUI that consumes them.  Appending
    # the texture after title_top.gui leaves its resource unresolved when the
    # GUI is instantiated, even though the ARC itself remains structurally
    # valid.  Keep the new texture beside the two existing title textures and
    # before title_top.gui.
    insert_at = next(
        index for index, entry in enumerate(entries) if entry.name == GUI_ENTRY
    )
    dlc_entry = new_texture_entry(panel, texture, insert_at)
    archive["entries"] = entries[:insert_at] + [dlc_entry] + entries[insert_at:]
    replacements = {GUI_ENTRY: gui, DLC_ENTRY: texture}
    output = build_arc_bytes(archive, replacements)

    verified = parse_arc(output)
    by_name = {entry.name: entry for entry in verified["entries"]}
    if by_name[GUI_ENTRY].data != gui or by_name[DLC_ENTRY].data != texture:
        raise ValueError("rebuilt DLC title resource failed verification")
    args.output_arc.parent.mkdir(parents=True, exist_ok=True)
    args.output_arc.write_bytes(output)
    print(
        f"wrote {args.output_arc} with {len(verified['entries'])} entries; "
        f"GUI {len(gui)} bytes"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
