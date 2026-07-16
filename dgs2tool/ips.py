"""Create and apply simple IPS patches suitable for Luma3DS code patching."""

from __future__ import annotations


MAGIC = b"PATCH"
EOF = b"EOF"
MAX_OFFSET = 0xFFFFFF
MAX_RECORD_SIZE = 0xFFFF


def create_ips(source: bytes, target: bytes) -> bytes:
    """Create a non-RLE IPS patch for equal-length files."""
    if len(source) != len(target):
        raise ValueError("IPS creation currently requires equal-length source and target files")
    if len(source) > MAX_OFFSET + 1:
        raise ValueError("input is too large for 24-bit IPS offsets")

    output = bytearray(MAGIC)
    cursor = 0
    while cursor < len(source):
        if source[cursor] == target[cursor]:
            cursor += 1
            continue
        start = cursor
        while cursor < len(source) and source[cursor] != target[cursor]:
            cursor += 1
        end = cursor

        # A record beginning with ASCII "EOF" would be mistaken for the
        # terminator. Include one unchanged preceding byte in that rare case.
        if start.to_bytes(3, "big") == EOF:
            start -= 1

        while start < end:
            chunk_end = min(start + MAX_RECORD_SIZE, end)
            data = target[start:chunk_end]
            output.extend(start.to_bytes(3, "big"))
            output.extend(len(data).to_bytes(2, "big"))
            output.extend(data)
            start = chunk_end

    output.extend(EOF)
    return bytes(output)


def apply_ips(source: bytes, patch: bytes) -> bytes:
    if not patch.startswith(MAGIC):
        raise ValueError("not an IPS patch")
    output = bytearray(source)
    cursor = len(MAGIC)
    while True:
        if cursor + 3 > len(patch):
            raise ValueError("truncated IPS record")
        marker = patch[cursor : cursor + 3]
        cursor += 3
        if marker == EOF:
            break
        offset = int.from_bytes(marker, "big")
        if cursor + 2 > len(patch):
            raise ValueError("truncated IPS record size")
        size = int.from_bytes(patch[cursor : cursor + 2], "big")
        cursor += 2
        if size:
            if cursor + size > len(patch):
                raise ValueError("truncated IPS record data")
            data = patch[cursor : cursor + size]
            cursor += size
        else:
            if cursor + 3 > len(patch):
                raise ValueError("truncated IPS RLE record")
            repeat = int.from_bytes(patch[cursor : cursor + 2], "big")
            value = patch[cursor + 2]
            cursor += 3
            data = bytes([value]) * repeat
        end = offset + len(data)
        if end > len(output):
            output.extend(b"\0" * (end - len(output)))
        output[offset:end] = data

    remaining = len(patch) - cursor
    if remaining == 3:
        final_size = int.from_bytes(patch[cursor:], "big")
        del output[final_size:]
    elif remaining:
        raise ValueError("unexpected data after IPS terminator")
    return bytes(output)
