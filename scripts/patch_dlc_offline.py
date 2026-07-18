#!/usr/bin/env python3
"""Patch DGS2 code.bin so installed DLC can be opened without NIM entitlement lookup."""

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
    args = parser.parse_args()

    data = bytearray(args.source.read_bytes())

    # The restored local catalogue uses its first DLC card. Skip the content
    # loop only for an empty list (BMI), not when exactly one card exists (BLE).
    replace(
        data,
        0x0021_3B80,
        bytes.fromhex("0c 00 00 da"),
        bytes.fromhex("0c 00 00 4a"),
    )

    # State 6 normally launches the NIM/AOC entitlement request.  Go straight
    # to state 9, which builds the DLC screen and reads the installed content.
    replace(
        data,
        0x0013_C61C,
        bytes.fromhex("cc 02 9f e5"),
        arm_branch(0x0013_C61C, 0x0013_C7E8),
    )

    # The four accessors expose the entitlement bits filled by that request.
    # For the offline build they report available; actual assets still have to
    # load from the installed Add-On Content archives.
    mov_r0_1_bx_lr = bytes.fromhex("01 00 a0 e3 1e ff 2f e1")
    for address, expected in (
        (0x004B_80B0, bytes.fromhex("0e 0a 80 e2 30 04 d0 e5")),
        (0x004B_80E8, bytes.fromhex("0e 0a 80 e2 30 04 d0 e5")),
        (0x004B_81F4, bytes.fromhex("0e 0a 80 e2 34 04 d0 e5")),
        (0x004B_8204, bytes.fromhex("0e 0a 80 e2 34 04 d0 e5")),
    ):
        replace(data, address, expected, mov_r0_1_bx_lr)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(data)


if __name__ == "__main__":
    main()
