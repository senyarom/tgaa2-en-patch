#!/usr/bin/env python3
"""Patch TGAA1 so installed Add-On Content can be opened offline."""

from __future__ import annotations

import argparse
import struct
from pathlib import Path


IMAGE_BASE = 0x0010_0000


def arm_branch(source: int, target: int) -> bytes:
    delta = target - (source + 8)
    if delta % 4:
        raise ValueError("ARM branch target is not word-aligned")
    immediate = (delta // 4) & 0x00FF_FFFF
    return struct.pack("<I", 0xEA00_0000 | immediate)


def replace(data: bytearray, address: int, expected: bytes, replacement: bytes) -> None:
    offset = address - IMAGE_BASE
    actual = bytes(data[offset : offset + len(expected)])
    if actual != expected:
        raise RuntimeError(
            f"unexpected bytes at 0x{address:08X}: "
            f"wanted {expected.hex()}, got {actual.hex()}"
        )
    data[offset : offset + len(replacement)] = replacement


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--display-version",
        help="version shown in Scarlet Study's ENG x.y.z label",
    )
    args = parser.parse_args()

    data = bytearray(args.source.read_bytes())

    # TGAA1 tracks its 15 DLC catalogue entries in two bit fields at manager
    # offsets 0xC474 and 0xC478.  The accessors at 0x39B064 and 0x39B1EC test
    # entry indices 0..14, so the complete local catalogue is 0x00007FFF in
    # both fields.  A debugger dump displayed its little-endian bytes as
    # ``FF 7F 00 00``; treating that byte sequence as 0xFF7F0000 leaves all
    # fifteen tested low bits clear and produces the "Purchase DLC" message.
    replace(
        data,
        0x001E_C3AC,
        bytes.fromhex("31 0b 80 e2"),  # add r0, r0, #0xC400
        bytes.fromhex("04 00 82 e2"),  # add r0, r2, #4
    )
    replace(
        data,
        0x001E_C3B0,
        bytes.fromhex("00 10 a0 e3"),  # mov r1, #0
        bytes.fromhex("7f 1c a0 e3"),  # mov r1, #0x00007F00 (ARMv6-safe)
    )
    replace(
        data,
        0x001E_C3B4,
        bytes.fromhex("78 00 80 e2"),  # add r0, r0, #0x78
        bytes.fromhex("ff 10 81 e3"),  # orr r1, r1, #0x000000FF
    )

    # Keep state 4's call to the initializer above, then skip the online task
    # and continue at state 7.  State 7 opens the catalogue; its availability
    # accessors now see both populated bit fields instead of zeroes.
    replace(
        data,
        0x0013_ADB4,
        bytes.fromhex("05 00 a0 e1"),  # mov r0, r5
        bytes.fromhex("07 00 a0 e3"),  # mov r0, #7
    )
    replace(
        data,
        0x0013_ADB8,
        bytes.fromhex("00 f0 20 e3"),  # nop
        arm_branch(0x0013_ADB8, 0x0013_ADD4),
    )

    # The DLC screen performs a second, independent status check after its
    # Add-On Content enumeration task completes.  Azahar reports status 0,
    # while retail hardware can report a network-era NIM/AOC error here.  The
    # original error branch stores action 2 in the GUI, which the parent screen
    # interprets as "return to title".  Always continue through the local
    # installed-content enumeration instead; the availability fields above
    # make an empty/failed online response safe as well.
    replace(
        data,
        0x001D_0C48,
        bytes.fromhex("0c 00 00 0a"),  # beq 0x001D0C80
        arm_branch(0x001D_0C48, 0x001D_0C80),
    )

    # Once enumeration has populated the local catalogue, state 6 builds the
    # actual DLC menu.  It consults the same obsolete NIM status object twice:
    # first after the menu-loading task, then again during task cleanup.  On a
    # retail 3DS either check can emit GUI action 2 (return to title) even
    # though the installed contents were found successfully.  Preserve the
    # normal local setup/cleanup paths and bypass only those automatic error
    # exits.  The user's Back command is handled elsewhere and remains intact.
    replace(
        data,
        0x001C_90D4,
        bytes.fromhex("06 00 00 0a"),  # beq 0x001C90F4
        arm_branch(0x001C_90D4, 0x001C_90F4),
    )
    replace(
        data,
        0x001C_9828,
        bytes.fromhex("0d 00 00 0a"),  # beq 0x001C9864 (return-to-title error)
        arm_branch(0x001C_9828, 0x001C_982C),
    )

    # Enumeration then enters GUI state 6.  Ignore the two stale NIM error
    # fields that make retail hardware return to the title screen, but keep the
    # original local-mount wait and validation path intact.  Jumping straight
    # to the success block is unsafe: it marks content mounted before FS has
    # actually opened it and produces the game's "data is corrupted" warning.
    replace(
        data,
        0x001C_C27C,
        bytes.fromhex("31 00 00 1a"),  # bne 0x001CC348 (return-to-title error)
        bytes.fromhex("00 f0 20 e3"),  # nop
    )
    replace(
        data,
        0x001C_C290,
        bytes.fromhex("2c 00 00 0a"),  # beq 0x001CC348 (return-to-title error)
        bytes.fromhex("00 f0 20 e3"),  # nop
    )

    # After the real local-content readiness check above succeeds, state 4
    # consults AOC status byte 0x16 once more.  Azahar reports zero and enters
    # the menu-building state directly.  Retail hardware can retain a stale
    # nonzero NIM status, which routes through state 5 and ultimately emits
    # action 2 (return to title).  Take the same local path as Azahar here;
    # importantly, the earlier readiness branch at 0x1CC2B8 remains intact.
    replace(
        data,
        0x001C_C384,
        bytes.fromhex("03 00 00 0a"),  # beq 0x001CC398
        arm_branch(0x001C_C384, 0x001C_C398),
    )

    if args.display_version is not None:
        display_version = args.display_version
        if len(display_version) == 1 and display_version.isdigit():
            display_version = f"2.7.{display_version}"
        if (
            len(display_version) != 5
            or display_version[1] != "."
            or display_version[3] != "."
            or not (display_version[0] + display_version[2] + display_version[4]).isdigit()
        ):
            parser.error("--display-version must look like 2.8.0")
        replace(data, 0x001D_6B8C, b"2.7.4", display_version.encode("ascii"))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(data)


if __name__ == "__main__":
    main()
