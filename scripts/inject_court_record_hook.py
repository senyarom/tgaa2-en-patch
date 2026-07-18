#!/usr/bin/env python3
"""Inject the Court Record hook payload into a decompressed code.bin."""

from __future__ import annotations

import argparse
import struct
from pathlib import Path


TGAA2_DEFAULTS = {
    "image_base": 0x0010_0000,
    "call_site": 0x0026_FC84,
    "hook_address": 0x005B_DA90,
    "code_cave_end": 0x005B_EA90,
    "expected_call": bytes.fromhex("99 08 00 eb"),  # BL 0x00271EF0
}


def arm_branch_link(source: int, target: int) -> bytes:
    delta = target - (source + 8)
    if delta % 4:
        raise ValueError("ARM branch target is not word-aligned")
    words = delta // 4
    if not -(1 << 23) <= words < (1 << 23):
        raise ValueError("ARM BL target is out of range")
    return struct.pack("<I", 0xEB00_0000 | (words & 0x00FF_FFFF))


def arm_branch_link_exchange(source: int, target: int) -> bytes:
    """Encode an ARM-state BLX immediate to an even Thumb entry address."""
    delta = target - (source + 8)
    if delta % 2:
        raise ValueError("Thumb branch target is not halfword-aligned")
    if not -(1 << 25) <= delta < (1 << 25):
        raise ValueError("ARM BLX target is out of range")
    h_bit = (delta >> 1) & 1
    words = delta >> 2
    return struct.pack(
        "<I",
        0xFA00_0000 | (h_bit << 24) | (words & 0x00FF_FFFF),
    )


def offset(address: int, image_base: int) -> int:
    return address - image_base


def parse_int(value: str) -> int:
    return int(value, 0)


def parse_bytes(value: str) -> bytes:
    return bytes.fromhex(value)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("payload", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--image-base", type=parse_int, default=TGAA2_DEFAULTS["image_base"])
    parser.add_argument("--call-site", type=parse_int, default=TGAA2_DEFAULTS["call_site"])
    parser.add_argument("--hook-address", type=parse_int, default=TGAA2_DEFAULTS["hook_address"])
    parser.add_argument("--code-cave-end", type=parse_int, default=TGAA2_DEFAULTS["code_cave_end"])
    parser.add_argument("--expected-call", type=parse_bytes, default=TGAA2_DEFAULTS["expected_call"])
    parser.add_argument(
        "--thumb-hook",
        action="store_true",
        help="patch the ARM call site with BLX to a Thumb payload",
    )
    args = parser.parse_args()

    data = bytearray(args.source.read_bytes())
    payload = args.payload.read_bytes()
    if not payload:
        raise RuntimeError("hook payload is empty")
    if args.hook_address + len(payload) > args.code_cave_end:
        raise RuntimeError(
            f"hook payload does not fit: {len(payload)} bytes at "
            f"0x{args.hook_address:08X}"
        )

    call_offset = offset(args.call_site, args.image_base)
    actual_call = bytes(data[call_offset : call_offset + len(args.expected_call)])
    if actual_call != args.expected_call:
        raise RuntimeError(
            f"unexpected call at 0x{args.call_site:08X}: "
            f"wanted {args.expected_call.hex()}, got {actual_call.hex()}"
        )

    hook_offset = offset(args.hook_address, args.image_base)
    cave = bytes(data[hook_offset : hook_offset + len(payload)])
    if cave != bytes(len(payload)):
        raise RuntimeError(
            f"code cave at 0x{args.hook_address:08X} is not empty: {cave.hex()}"
        )

    data[hook_offset : hook_offset + len(payload)] = payload
    if args.thumb_hook:
        patched_call = arm_branch_link_exchange(args.call_site, args.hook_address)
    else:
        patched_call = arm_branch_link(args.call_site, args.hook_address)
    data[call_offset : call_offset + 4] = patched_call

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(data)
    print(
        f"Injected {len(payload)} bytes at 0x{args.hook_address:08X}; "
        f"patched BL at 0x{args.call_site:08X} ({patched_call.hex()})."
    )


if __name__ == "__main__":
    main()
