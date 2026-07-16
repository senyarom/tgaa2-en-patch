"""Read and extract little/big-endian Capcom MT Framework ARC archives."""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


EXTENSIONS = {
    0xA42BB29A: ".gmd",
    0x242BB29A: ".gmd",
    0xA2948394: ".gui",
    0x22948394: ".gui",
    0xA41F5DEB: ".tex",
    0x241F5DEB: ".tex",
    0xF3850D05: ".arc",
    0x73850D05: ".arc",
    0xAD462600: ".gfd",
    0x2D462600: ".gfd",
}


@dataclass(frozen=True)
class ArcEntry:
    index: int
    name: str
    extension_hash: int
    compressed_size: int
    decompressed_size: int
    offset: int
    compressed: bool
    data: bytes
    stored_data: bytes
    raw_name: bytes
    raw_decompressed_size: int


def _decode_name(raw: bytes) -> str:
    value = raw.split(b"\0", 1)[0].decode("utf-8", errors="strict").replace("\\", "/")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"unsafe ARC entry path: {value!r}")
    return path.as_posix()


def _extension(value: int) -> str:
    return EXTENSIONS.get(value, f".{value:08X}")


def _decompressed_size(raw: int, endian: str) -> int:
    return raw & 0x00FFFFFF if endian == "<" else raw >> 3


def parse_arc(blob: bytes) -> dict:
    if len(blob) < 8:
        raise ValueError("truncated ARC header")
    if blob[:4] == b"ARC\0":
        endian = "<"
    elif blob[:4] == b"\0CRA":
        endian = ">"
    else:
        raise ValueError("not an MT Framework ARC")

    version, count = struct.unpack_from(endian + "hh", blob, 4)
    if count < 0:
        raise ValueError("negative ARC entry count")
    if version == 9:
        raise ValueError("Switch ARC v9 is not supported by this extractor")

    entry_offset = 8
    if endian == "<" and version not in (7, 8):
        entry_offset += 4

    extended_names = False
    if count:
        if entry_offset + 0x50 > len(blob):
            raise ValueError("truncated first ARC entry")
        _name, extension_hash, _comp, raw_decomp, data_offset = struct.unpack_from(
            endian + "64sIiii", blob, entry_offset
        )
        extended_names = extension_hash == 0 or raw_decomp == 0 or data_offset == 0

    name_size = 0x80 if extended_names else 0x40
    entry_size = name_size + 0x10
    entries: list[ArcEntry] = []

    for index in range(count):
        offset = entry_offset + index * entry_size
        if offset + entry_size > len(blob):
            raise ValueError("truncated ARC entry table")
        raw_name, extension_hash, comp_size, raw_decomp, data_offset = struct.unpack_from(
            endian + f"{name_size}sIiii", blob, offset
        )
        decomp_size = _decompressed_size(raw_decomp, endian)
        if min(comp_size, decomp_size, data_offset) < 0 or data_offset + comp_size > len(blob):
            raise ValueError(f"ARC entry {index} is out of bounds")

        stored = blob[data_offset : data_offset + comp_size]
        compressed = comp_size != decomp_size
        if compressed:
            try:
                data = zlib.decompress(stored)
            except zlib.error as exc:
                raise ValueError(f"ARC entry {index} is marked compressed but is not zlib") from exc
            if len(data) != decomp_size:
                raise ValueError(f"ARC entry {index} decompressed size mismatch")
        else:
            data = stored

        base_name = _decode_name(raw_name)
        entries.append(
            ArcEntry(
                index=index,
                name=base_name + _extension(extension_hash),
                extension_hash=extension_hash,
                compressed_size=comp_size,
                decompressed_size=decomp_size,
                offset=data_offset,
                compressed=compressed,
                data=data,
                stored_data=stored,
                raw_name=raw_name,
                raw_decompressed_size=raw_decomp,
            )
        )

    return {
        "version": version,
        "endian": "little" if endian == "<" else "big",
        "extended_names": extended_names,
        "header_extra": blob[8:entry_offset],
        "entries": entries,
    }


def build_arc_bytes(archive: dict, replacements: dict[str, bytes] | None = None) -> bytes:
    """Rebuild an ARC while preserving its original entry organization."""
    replacements = replacements or {}
    entries: list[ArcEntry] = archive["entries"]
    unknown = sorted(set(replacements) - {entry.name for entry in entries})
    if unknown:
        raise ValueError(f"ARC replacement paths do not exist: {', '.join(unknown)}")

    endian = "<" if archive["endian"] == "little" else ">"
    magic = b"ARC\0" if endian == "<" else b"\0CRA"
    header_extra = archive.get("header_extra", b"")
    name_size = 0x80 if archive["extended_names"] else 0x40
    entry_size = name_size + 0x10
    table_end = 8 + len(header_extra) + len(entries) * entry_size
    data_offset = min((entry.offset for entry in entries), default=table_end)
    if data_offset < table_end:
        raise ValueError("ARC data overlaps its entry table")

    stored_entries: list[tuple[ArcEntry, bytes, int]] = []
    for entry in entries:
        if entry.name not in replacements:
            stored_entries.append((entry, entry.stored_data, entry.decompressed_size))
            continue
        data = replacements[entry.name]
        stored = zlib.compress(data, level=9) if entry.compressed else data
        stored_entries.append((entry, stored, len(data)))

    output = bytearray(data_offset)
    output[:8] = struct.pack(endian + "4shh", magic, archive["version"], len(entries))
    output[8 : 8 + len(header_extra)] = header_extra

    current_offset = data_offset
    table_offset = 8 + len(header_extra)
    for index, (entry, stored, decompressed_size) in enumerate(stored_entries):
        if endian == "<":
            raw_decompressed = (entry.raw_decompressed_size & ~0x00FFFFFF) | decompressed_size
        else:
            raw_decompressed = (entry.raw_decompressed_size & 0x00000007) | (decompressed_size << 3)
        record = struct.pack(
            endian + f"{name_size}sIiii",
            entry.raw_name,
            entry.extension_hash,
            len(stored),
            raw_decompressed,
            current_offset,
        )
        start = table_offset + index * entry_size
        output[start : start + entry_size] = record
        output.extend(stored)
        current_offset += len(stored)
    return bytes(output)


def rebuild_arc(input_path: Path, replacements_root: Path, output_path: Path) -> dict:
    archive = parse_arc(input_path.read_bytes())
    replacements: dict[str, bytes] = {}
    for entry in archive["entries"]:
        relative = PurePosixPath(entry.name)
        candidate = replacements_root.joinpath(*relative.parts)
        if candidate.is_file():
            replacements[entry.name] = candidate.read_bytes()

    output = build_arc_bytes(archive, replacements)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(output)
    verified = parse_arc(output)
    for entry in verified["entries"]:
        expected = replacements.get(entry.name)
        if expected is not None and entry.data != expected:
            raise ValueError(f"ARC replacement verification failed: {entry.name}")
    return {
        "input": str(input_path),
        "output": str(output_path),
        "replaced_count": len(replacements),
        "replaced": sorted(replacements),
        "entry_count": len(verified["entries"]),
        "output_size": len(output),
    }


def extract_arc(input_path: Path, output_dir: Path, only_gmd: bool = False) -> dict:
    archive = parse_arc(input_path.read_bytes())
    output_dir.mkdir(parents=True, exist_ok=True)
    extracted: list[dict] = []

    for entry in archive["entries"]:
        if only_gmd and not entry.name.lower().endswith(".gmd"):
            continue
        relative = PurePosixPath(entry.name)
        destination = output_dir.joinpath(*relative.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(entry.data)
        extracted.append(
            {
                "name": entry.name,
                "size": len(entry.data),
                "compressed": entry.compressed,
                "extension_hash": f"{entry.extension_hash:08x}",
            }
        )

    return {
        "archive": str(input_path),
        "version": archive["version"],
        "endian": archive["endian"],
        "extended_names": archive["extended_names"],
        "extracted_count": len(extracted),
        "files": extracted,
    }
