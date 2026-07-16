"""Extract the small ustar filesystem embedded in a GodMode9 FIRM payload."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath


BLOCK_SIZE = 512


@dataclass(frozen=True)
class FirmEntry:
    name: str
    header_offset: int
    size: int
    data: bytes


def _parse_octal(field: bytes) -> int:
    value = field.split(b"\0", 1)[0].strip()
    return int(value or b"0", 8)


def _safe_name(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"unsafe embedded path: {name!r}")
    return path


def iter_entries(blob: bytes):
    """Yield aligned ustar entries found anywhere inside a FIRM image."""
    offset = 0
    limit = len(blob) - BLOCK_SIZE
    while offset <= limit:
        header = blob[offset : offset + BLOCK_SIZE]
        if header[257:262] != b"ustar":
            offset += BLOCK_SIZE
            continue

        raw_name = header[:100].split(b"\0", 1)[0]
        try:
            name = raw_name.decode("utf-8")
            size = _parse_octal(header[124:136])
        except (UnicodeDecodeError, ValueError):
            offset += BLOCK_SIZE
            continue

        _safe_name(name)
        start = offset + BLOCK_SIZE
        end = start + size
        if end > len(blob):
            raise ValueError(f"truncated embedded file {name!r}")

        yield FirmEntry(name=name, header_offset=offset, size=size, data=blob[start:end])
        offset = start + ((size + BLOCK_SIZE - 1) // BLOCK_SIZE) * BLOCK_SIZE


def extract_firm(firm_path: Path, output_dir: Path) -> list[FirmEntry]:
    blob = firm_path.read_bytes()
    entries = list(iter_entries(blob))
    if not entries:
        raise ValueError("no aligned ustar entries found in FIRM")

    output_dir.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        relative = _safe_name(entry.name)
        destination = output_dir.joinpath(*relative.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(entry.data)
    return entries
