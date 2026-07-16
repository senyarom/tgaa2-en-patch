"""Minimal, dependency-free Beat Patch System (BPS1) reader and applier."""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass


@dataclass
class _Reader:
    data: bytes
    offset: int = 0

    def read(self, size: int) -> bytes:
        end = self.offset + size
        if end > len(self.data):
            raise ValueError("truncated BPS patch")
        result = self.data[self.offset:end]
        self.offset = end
        return result

    def number(self) -> int:
        value = 0
        shift = 1
        while True:
            byte = self.read(1)[0]
            value += (byte & 0x7F) * shift
            if byte & 0x80:
                return value
            shift <<= 7
            value += shift

    def signed_number(self) -> int:
        value = self.number()
        magnitude = value >> 1
        return -magnitude if value & 1 else magnitude


def _crc(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


def _header(patch: bytes) -> tuple[_Reader, int, int, bytes]:
    if len(patch) < 16 or patch[:4] != b"BPS1":
        raise ValueError("not a BPS1 patch")
    reader = _Reader(patch, 4)
    source_size = reader.number()
    target_size = reader.number()
    metadata_size = reader.number()
    metadata = reader.read(metadata_size)
    return reader, source_size, target_size, metadata


def inspect_bps(patch: bytes) -> dict:
    reader, source_size, target_size, metadata = _header(patch)
    action_end = len(patch) - 12
    if reader.offset > action_end:
        raise ValueError("invalid BPS action stream")

    output_size = 0
    counts = {"source_read": 0, "target_read": 0, "source_copy": 0, "target_copy": 0}
    names = tuple(counts)
    while reader.offset < action_end:
        action = reader.number()
        mode = action & 3
        length = (action >> 2) + 1
        counts[names[mode]] += 1
        output_size += length
        if mode == 1:
            reader.read(length)
        elif mode in (2, 3):
            reader.signed_number()

    if reader.offset != action_end:
        raise ValueError("BPS action stream crossed checksum boundary")

    source_crc, target_crc, patch_crc = struct.unpack_from("<III", patch, action_end)
    return {
        "source_size": source_size,
        "target_size": target_size,
        "metadata": metadata.decode("utf-8", errors="replace"),
        "action_output_size": output_size,
        "actions": counts,
        "source_crc32": f"{source_crc:08x}",
        "target_crc32": f"{target_crc:08x}",
        "patch_crc32": f"{patch_crc:08x}",
        "computed_patch_crc32": f"{_crc(patch[:-4]):08x}",
        "patch_crc_valid": _crc(patch[:-4]) == patch_crc,
    }


def apply_bps(source: bytes, patch: bytes) -> bytes:
    reader, source_size, target_size, _metadata = _header(patch)
    action_end = len(patch) - 12
    if len(source) != source_size:
        raise ValueError(f"BPS source size mismatch: expected {source_size}, got {len(source)}")

    source_crc, target_crc, patch_crc = struct.unpack_from("<III", patch, action_end)
    if _crc(source) != source_crc:
        raise ValueError("BPS source CRC32 mismatch")
    if _crc(patch[:-4]) != patch_crc:
        raise ValueError("BPS patch CRC32 mismatch")

    output = bytearray()
    source_relative = 0
    target_relative = 0

    while reader.offset < action_end and len(output) < target_size:
        action = reader.number()
        mode = action & 3
        length = (action >> 2) + 1

        if mode == 0:  # SourceRead at current target offset
            start = len(output)
            end = start + length
            if end > len(source):
                raise ValueError("BPS SourceRead is out of bounds")
            output.extend(source[start:end])
        elif mode == 1:  # TargetRead literal bytes
            output.extend(reader.read(length))
        elif mode == 2:  # SourceCopy at a relative source offset
            source_relative += reader.signed_number()
            end = source_relative + length
            if source_relative < 0 or end > len(source):
                raise ValueError("BPS SourceCopy is out of bounds")
            output.extend(source[source_relative:end])
            source_relative = end
        else:  # TargetCopy, supporting overlap
            target_relative += reader.signed_number()
            if target_relative < 0:
                raise ValueError("BPS TargetCopy is out of bounds")
            for _ in range(length):
                if target_relative >= len(output):
                    raise ValueError("BPS TargetCopy reads unwritten output")
                output.append(output[target_relative])
                target_relative += 1

    if reader.offset != action_end:
        raise ValueError("unexpected trailing BPS actions")
    if len(output) != target_size:
        raise ValueError(f"BPS target size mismatch: expected {target_size}, got {len(output)}")
    if _crc(output) != target_crc:
        raise ValueError("BPS target CRC32 mismatch")
    return bytes(output)
