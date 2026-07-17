#!/usr/bin/env python3
"""Re-enable TGAA1's DLC panel without changing Scarlet Study's animations.

Scarlet Study retained all ten nodes of the Japanese DLC panel, but hid them
by setting their Visible values to zero and moving nine of them to X=-500.
The English label animations are otherwise valid and must not be expanded or
reindexed.  This patch restores only the static visibility and X positions.
"""

from __future__ import annotations

import argparse
import struct
from pathlib import Path


NODE_START = 0x2D0
NODE_SIZE = 0x24
NODE_COUNT = 72

DLC_NODES = (
    "Null_title_panel_02",
    "panel_cursor_02",
    "panel_frame_02",
    "panel_text_02",
    "panel_textbase_02",
    "panel_effect_02",
    "panel_base_02",
    "panel_textbase_02_light",
    "Null_panel_flash_02",
    "panel_flash_02",
)

# Scarlet Study laid the surviving New Game/Continue and Select Episode cards
# out as a two-card menu after removing DLC.  Their Japanese source GUI keeps
# the three-card coordinates we need.  Restoring these roots puts the active
# New Game/Continue card between DLC and Select Episode again.
THREE_CARD_LAYOUT_NODES = (
    "Null_title_panel_00",
    "hajimekara_01",
    "Null_panel_flash_00",
    "Null_title_panel_03",
    "erabu_01",
    "Null_panel_flash_03",
    "Null_title_panel_04",
    "tudukikara_01",
    "Null_panel_flash_04",
)

# Scarlet removed two DLC-only X coordinates from its float pool.  Reuse the
# closest existing coordinate instead of overwriting or extending that pool:
# its scalar values are also consumed by animation channels.
POSITION_FALLBACKS = {
    -8.0: -18.0,
    -15.0: -18.0,
}


def u32(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def set_u32(data: bytearray, offset: int, value: int) -> None:
    struct.pack_into("<I", data, offset, value)


def cstring(data: bytes | bytearray, offset: int) -> str:
    end = data.find(b"\0", offset)
    if end < 0:
        raise ValueError("unterminated GUI string")
    return bytes(data[offset:end]).decode("ascii")


def nodes(data: bytes | bytearray) -> list[tuple[str, int]]:
    string_pool = u32(data, 0x104)
    result: list[tuple[str, int]] = []
    for index in range(NODE_COUNT):
        offset = NODE_START + index * NODE_SIZE
        name = cstring(data, string_pool + u32(data, offset + 20))
        property_start = u32(data, offset + 28)
        result.append((name, property_start))
    return result


def property_layout(data: bytes | bytearray) -> tuple[int, int]:
    """Return the first property record and its stride.

    Capcom's original GUI stores 16-byte property records.  Scarlet Study's
    rebuilt GUI uses the extended 20-byte form, with a four-byte prefix and
    suffix around the property array.  Node property indices are unchanged.
    """

    property_pool = u32(data, 0xB4)
    property_end = u32(data, 0xB8)
    property_count = u32(data, 0x38)
    span = property_end - property_pool
    if span == property_count * 0x10:
        return property_pool, 0x10
    if span == property_count * 0x14 + 8:
        return property_pool + 4, 0x14
    raise ValueError(
        "unsupported GUI property layout: "
        f"span=0x{span:X}, count={property_count}"
    )


def node_properties(
    data: bytes | bytearray,
) -> dict[str, dict[str, tuple[int, int, int]]]:
    property_pool, property_size = property_layout(data)
    string_pool = u32(data, 0x104)
    node_list = nodes(data)
    property_count = u32(data, 0x38)
    result: dict[str, dict[str, tuple[int, int, int]]] = {}
    for index, (node_name, start) in enumerate(node_list):
        end = node_list[index + 1][1] if index + 1 < len(node_list) else property_count
        properties: dict[str, tuple[int, int, int]] = {}
        for property_index in range(start, end):
            offset = property_pool + property_index * property_size
            property_type = u32(data, offset)
            property_name = cstring(data, string_pool + u32(data, offset + 8))
            value_offset = u32(data, offset + 12)
            properties[property_name] = (property_type, value_offset, offset)
        result[node_name] = properties
    return result


def float_value(data: bytes | bytearray, offset: int) -> float:
    return struct.unpack_from("<f", data, u32(data, 0x110) + offset)[0]


def find_float_offset(data: bytes | bytearray, value: float) -> int | None:
    start = u32(data, 0x110)
    end = u32(data, 0x114)
    wanted = struct.pack("<f", value)
    for offset in range(0, end - start, 4):
        if data[start + offset : start + offset + 4] == wanted:
            return offset
    return None


def patch_gui(
    base: bytes,
    scarlet: bytes,
    *,
    restore_positions: bool = True,
    restore_visibility: bool = True,
    restore_layout: bool = True,
) -> bytes:
    if base[:4] != b"GUI\0" or scarlet[:4] != b"GUI\0":
        raise ValueError("input is not an MT Framework GUI file")

    output = bytearray(scarlet)
    base_properties = node_properties(base)
    scarlet_properties = node_properties(output)
    byte_pool = u32(output, 0x10C)
    for node_name in DLC_NODES:
        if restore_positions:
            base_posx = base_properties[node_name]["PosX"]
            scarlet_posx = scarlet_properties[node_name]["PosX"]
            if base_posx[0] & 0xFF != 2 or scarlet_posx[0] & 0xFF != 2:
                raise ValueError(f"unexpected PosX type for {node_name}")

            desired_value = float_value(base, base_posx[1])
            target_offset = find_float_offset(output, desired_value)
            if target_offset is None:
                fallback_value = POSITION_FALLBACKS.get(desired_value)
                if fallback_value is None:
                    raise ValueError(
                        f"Scarlet float pool has no X coordinate {desired_value:g}"
                    )
                target_offset = find_float_offset(output, fallback_value)
                if target_offset is None:
                    raise ValueError(
                        f"Scarlet float pool has no fallback X coordinate "
                        f"{fallback_value:g}"
                    )
            set_u32(output, scarlet_posx[2] + 12, target_offset)

        if restore_visibility:
            base_visible = base_properties[node_name]["Visible"]
            scarlet_visible = scarlet_properties[node_name]["Visible"]
            if base_visible[0] & 0xFF != 3 or scarlet_visible[0] & 0xFF != 3:
                raise ValueError(f"unexpected Visible type for {node_name}")
            desired_visible = base[u32(base, 0x10C) + base_visible[1]]
            output[byte_pool + scarlet_visible[1]] = desired_visible

    if restore_layout:
        for node_name in THREE_CARD_LAYOUT_NODES:
            base_posx = base_properties[node_name]["PosX"]
            scarlet_posx = scarlet_properties[node_name]["PosX"]
            if base_posx[0] & 0xFF != 2 or scarlet_posx[0] & 0xFF != 2:
                raise ValueError(f"unexpected PosX type for {node_name}")
            desired_value = float_value(base, base_posx[1])
            target_offset = find_float_offset(output, desired_value)
            if target_offset is None:
                raise ValueError(
                    f"Scarlet float pool has no layout coordinate {desired_value:g}"
                )
            set_u32(output, scarlet_posx[2] + 12, target_offset)

    return bytes(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--scarlet", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--mode",
        choices=("all", "positions", "visibility", "layout"),
        default="all",
        help="select which hidden DLC properties to restore",
    )
    args = parser.parse_args()

    patched = patch_gui(
        args.base.read_bytes(),
        args.scarlet.read_bytes(),
        restore_positions=args.mode in ("all", "positions"),
        restore_visibility=args.mode in ("all", "visibility"),
        restore_layout=args.mode in ("all", "layout"),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(patched)
    print(f"wrote {args.output} ({len(patched)} bytes)")


if __name__ == "__main__":
    main()
