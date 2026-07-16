"""Read and rebuild Capcom MT Framework GMD v1/v2 text containers.

The format implementation follows the behavior of the GPL-3.0 Kuriimu2 GMD
plugin while exposing a stable, reviewable JSON interchange format.
"""

from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path


HEADER_SIZE = 0x28
VERSION_V1 = 0x00010201
VERSION_V2 = 0x00010302
KEY1 = (
    b"fjfajfahajra;tira9tgujagjjgajgoa",
    b"e43bcc7fcab+a6c4ed22fcd433/9d2e6cb053fa462-463f3a446b19",
)
KEY2 = (
    b"mva;eignhpe/dfkfjgp295jtugkpejfu",
    b"861f1dca05a0;9ddd5261e5dcc@6b438e6c.8ba7d71c*4fd11f3af1",
)


def _endian(blob: bytes) -> str:
    if blob[:4] == b"GMD\0":
        return "<"
    if blob[:4] == b"\0DMG":
        return ">"
    raise ValueError("not a GMD file")


def _decode_utf8(data: bytes) -> str:
    return data.decode("utf-8")


def _read_cstring(blob: bytes, offset: int, limit: int | None = None) -> tuple[str, int]:
    upper = len(blob) if limit is None else min(limit, len(blob))
    end = blob.find(b"\0", offset, upper)
    if end < 0:
        raise ValueError("unterminated GMD string")
    return _decode_utf8(blob[offset:end]), end + 1


def _candidate_score(data: bytes, section_count: int) -> tuple[int, int] | None:
    """Score a decoded text body, rejecting impossible section layouts.

    Some key-pair 1 files end on a zero byte because that XOR key contains
    zeroes.  Looking only at the final byte therefore mistakes those files
    for plaintext.  The complete section layout is a stronger signal.
    """
    if section_count == 0:
        return (0, 0) if not data else None
    if not data.endswith(b"\0") or data.count(0) != section_count:
        return None

    sections = data[:-1].split(b"\0")
    valid_utf8 = 0
    printable = 0
    for section in sections:
        try:
            text = section.decode("utf-8")
        except UnicodeDecodeError:
            continue
        valid_utf8 += 1
        printable += sum(character.isprintable() or character in "\r\n\t" for character in text)
    return valid_utf8, printable


def _detect_keypair(
    blob: bytes,
    text_offset: int,
    section_size: int | None = None,
    section_count: int | None = None,
) -> int:
    if text_offset >= len(blob):
        return -1

    if section_size is not None and section_count is not None:
        encrypted = blob[text_offset : text_offset + section_size]
        candidates: list[tuple[tuple[int, int], int]] = []
        for keypair in (-1, 0, 1):
            score = _candidate_score(_xor(encrypted, keypair), section_count)
            if score is not None:
                candidates.append((score, keypair))
        if candidates:
            return max(candidates)[1]

    # Compatibility fallback for callers that do not know the section layout.
    last = blob[-1]
    if last == 0:
        return -1
    for index, (left, right) in enumerate(zip(KEY1, KEY2)):
        key_position = (len(blob) - text_offset - 1) % len(left)
        if last ^ left[key_position] ^ right[key_position] == 0:
            return index
    raise ValueError("could not determine GMD XOR key pair")


def _xor(data: bytes, keypair: int) -> bytes:
    if keypair == -1:
        return data
    if keypair not in (0, 1):
        raise ValueError(f"unsupported GMD XOR key pair {keypair}")
    key = bytes(a ^ b for a, b in zip(KEY1[keypair], KEY2[keypair]))
    return bytes(value ^ key[index % len(key)] for index, value in enumerate(data))


def _split_sections(data: bytes, count: int) -> list[bytes]:
    sections: list[bytes] = []
    offset = 0
    for _ in range(count):
        end = data.find(b"\0", offset)
        if end < 0:
            raise ValueError("GMD text section is missing a terminator")
        sections.append(data[offset:end])
        offset = end + 1
    return sections


def _entry(index: int, label: str | None, data: bytes) -> dict:
    try:
        text: str | None = data.decode("utf-8")
    except UnicodeDecodeError:
        text = None
    return {"index": index, "label": label, "text": text, "text_hex": data.hex()}


def parse_gmd_bytes(blob: bytes) -> dict:
    endian = _endian(blob)
    if len(blob) < HEADER_SIZE:
        raise ValueError("truncated GMD header")

    magic, version, language, unknown, label_count, section_count, label_size, section_size, name_size = struct.unpack_from(
        endian + "4sIIqiiiii", blob, 0
    )
    if version not in (VERSION_V1, VERSION_V2):
        raise ValueError(f"unsupported GMD version 0x{version:08x}")
    if min(label_count, section_count, label_size, section_size, name_size) < 0:
        raise ValueError("negative GMD header field")

    name_start = HEADER_SIZE
    name_end = name_start + name_size
    if name_end >= len(blob) or blob[name_end] != 0:
        raise ValueError("invalid GMD name field")
    name = _decode_utf8(blob[name_start:name_end])
    entries_start = name_end + 1

    labels_by_section: dict[int, str] = {}
    platform = "default"
    label_obscure = 0
    mobile_padding = 0

    if version == VERSION_V1:
        entry_size = 8
        labels_start = entries_start + label_count * entry_size
        labels_end = labels_start + label_size
        if labels_end + section_size > len(blob):
            raise ValueError("truncated GMD v1 body")
        label_records = [
            struct.unpack_from(endian + "ii", blob, entries_start + index * entry_size)
            for index in range(label_count)
        ]
        label_obscure = label_records[0][1] if label_records else 0
        for section_id, label_offset in label_records:
            label, _ = _read_cstring(blob, labels_start + label_offset - label_obscure, labels_end)
            labels_by_section[section_id] = label
        text_start = labels_end
    else:
        default_size = (
            HEADER_SIZE
            + name_size
            + 1
            + label_count * 0x14
            + (0x400 if label_count else 0)
            + label_size
            + section_size
        )
        platform = "default" if default_size == len(blob) else "mobile"
        entry_size = 0x14 if platform == "default" else 0x20
        bucket_size = (0x400 if platform == "default" else 0x800) if label_count else 0
        labels_start = entries_start + label_count * entry_size + bucket_size
        labels_end = labels_start + label_size
        if labels_end + section_size > len(blob):
            raise ValueError("truncated GMD v2 body")

        for index in range(label_count):
            offset = entries_start + index * entry_size
            if platform == "default":
                section_id, _hash1, _hash2, label_offset, _link = struct.unpack_from(endian + "iIIii", blob, offset)
            else:
                section_id, _hash1, _hash2, padding, label_offset, _link = struct.unpack_from(endian + "iIIIqq", blob, offset)
                if index == 0:
                    mobile_padding = padding
            label, _ = _read_cstring(blob, labels_start + label_offset, labels_end)
            labels_by_section[section_id] = label
        text_start = labels_end

    keypair = _detect_keypair(blob, text_start, section_size, section_count)
    encrypted_text = blob[text_start : text_start + section_size]
    sections = _split_sections(_xor(encrypted_text, keypair), section_count)
    entries = [_entry(index, labels_by_section.get(index), data) for index, data in enumerate(sections)]

    return {
        "schema": 1,
        "format": "gmd",
        "metadata": {
            "endian": "little" if endian == "<" else "big",
            "version": version,
            "language": language,
            "unknown": unknown,
            "name": name,
            "platform": platform,
            "xor_keypair": keypair,
            "label_obscure": label_obscure,
            "mobile_padding": mobile_padding,
        },
        "entries": entries,
    }


def _entry_bytes(entry: dict) -> bytes:
    text = entry.get("text")
    if text is not None:
        return text.encode("utf-8")
    return bytes.fromhex(entry.get("text_hex", ""))


def _crc32b(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


def _label_hash(name: str, repetitions: int) -> int:
    encoded = (name * repetitions).encode("ascii", errors="replace")
    return (~_crc32b(encoded)) & 0xFFFFFFFF


def _bucket(name: str) -> int:
    return (~_crc32b(name.encode("ascii", errors="replace"))) & 0xFF


def _pack_header(endian: str, metadata: dict, label_count: int, section_count: int, label_size: int, section_size: int, name_size: int) -> bytes:
    magic = b"GMD\0" if endian == "<" else b"\0DMG"
    return struct.pack(
        endian + "4sIIqiiiii",
        magic,
        int(metadata["version"]),
        int(metadata.get("language", 0)),
        int(metadata.get("unknown", 0)),
        label_count,
        section_count,
        label_size,
        section_size,
        name_size,
    )


def build_gmd_bytes(document: dict) -> bytes:
    if document.get("format") != "gmd":
        raise ValueError("JSON document is not a GMD export")
    metadata = document["metadata"]
    entries = document["entries"]
    endian = "<" if metadata.get("endian", "little") == "little" else ">"
    version = int(metadata["version"])
    name_bytes = metadata.get("name", "").encode("utf-8")

    raw_text = b"".join(_entry_bytes(entry) + b"\0" for entry in entries)
    encrypted_text = _xor(raw_text, int(metadata.get("xor_keypair", -1)))

    named = [(index, entry["label"]) for index, entry in enumerate(entries) if entry.get("label") is not None]
    labels = bytearray()

    if version == VERSION_V1:
        obscure = int(metadata.get("label_obscure", 0))
        records = bytearray()
        for section_id, label in named:
            label_bytes = str(label).encode("utf-8")
            records.extend(struct.pack(endian + "ii", section_id, obscure + len(labels)))
            labels.extend(label_bytes + b"\0")
        body = bytes(records) + bytes(labels) + encrypted_text
    elif version == VERSION_V2:
        platform = metadata.get("platform", "default")
        mobile = platform == "mobile"
        label_metadata: list[dict] = []
        bucket_lookup: dict[int, int] = {}

        for section_id, label_value in named:
            label = str(label_value)
            current = len(label_metadata)
            bucket = _bucket(label)
            record = {
                "section_id": section_id,
                "hash1": _label_hash(label, 2),
                "hash2": _label_hash(label, 3),
                "label_offset": len(labels),
                "list_link": 0,
                "bucket": bucket,
            }
            if bucket in bucket_lookup:
                label_metadata[bucket_lookup[bucket]]["list_link"] = current
            bucket_lookup[bucket] = current
            label_metadata.append(record)
            labels.extend(label.encode("utf-8") + b"\0")

        records = bytearray()
        for record in label_metadata:
            if mobile:
                records.extend(
                    struct.pack(
                        endian + "iIIIqq",
                        record["section_id"],
                        record["hash1"],
                        record["hash2"],
                        int(metadata.get("mobile_padding", 0)),
                        record["label_offset"],
                        record["list_link"],
                    )
                )
            else:
                records.extend(
                    struct.pack(
                        endian + "iIIii",
                        record["section_id"],
                        record["hash1"],
                        record["hash2"],
                        record["label_offset"],
                        record["list_link"],
                    )
                )

        if label_metadata:
            buckets = [0] * 0x100
            for index, record in enumerate(label_metadata):
                bucket = record["bucket"]
                if buckets[bucket] == 0:
                    buckets[bucket] = -1 if index == 0 else index
            bucket_blob = struct.pack(endian + ("256q" if mobile else "256i"), *buckets)
        else:
            bucket_blob = b""
        body = bytes(records) + bucket_blob + bytes(labels) + encrypted_text
    else:
        raise ValueError(f"unsupported GMD version 0x{version:08x}")

    header = _pack_header(
        endian,
        metadata,
        len(named),
        len(entries),
        len(labels),
        len(encrypted_text),
        len(name_bytes),
    )
    return header + name_bytes + b"\0" + body


def dump_gmd(input_path: Path, output_path: Path) -> dict:
    document = parse_gmd_bytes(input_path.read_bytes())
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return document


def build_gmd(input_path: Path, output_path: Path) -> bytes:
    document = json.loads(input_path.read_text(encoding="utf-8"))
    blob = build_gmd_bytes(document)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(blob)
    return blob


def semantic_signature(document: dict) -> tuple:
    metadata = document["metadata"]
    return (
        metadata["version"],
        metadata["language"],
        metadata["name"],
        tuple((entry.get("label"), _entry_bytes(entry)) for entry in document["entries"]),
    )
