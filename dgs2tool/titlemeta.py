"""Helpers for patching Nintendo 3DS title and Add-On Content metadata."""

from __future__ import annotations


SMDH_MAGIC = b"SMDH"
SMDH_SIZE = 0x36C0
SMDH_TITLE_OFFSET = 0x8
SMDH_TITLE_SIZE = 0x200
SMDH_LANGUAGE_COUNT = 16


def _encode_utf16_field(value: str, size: int) -> bytes:
    encoded = value.encode("utf-16le")
    if len(encoded) + 2 > size:
        raise ValueError(f"SMDH text does not fit in a {size}-byte field: {value!r}")
    return encoded + bytes(size - len(encoded))


def patch_smdh_titles(
    source: bytes,
    *,
    short_description: str,
    long_description: str,
    publisher: str,
) -> bytes:
    """Replace every language title while retaining original SMDH artwork."""

    if len(source) != SMDH_SIZE or source[:4] != SMDH_MAGIC:
        raise ValueError("input is not a complete Nintendo 3DS SMDH")

    short_field = _encode_utf16_field(short_description, 0x80)
    long_field = _encode_utf16_field(long_description, 0x100)
    publisher_field = _encode_utf16_field(publisher, 0x80)

    output = bytearray(source)
    title = short_field + long_field + publisher_field
    for language in range(SMDH_LANGUAGE_COUNT):
        offset = SMDH_TITLE_OFFSET + language * SMDH_TITLE_SIZE
        output[offset : offset + SMDH_TITLE_SIZE] = title
    return bytes(output)


def _replace_utf8_field(
    data: bytearray,
    *,
    offset: int,
    size: int,
    expected: str,
    replacement: str,
) -> None:
    actual = bytes(data[offset : offset + size])
    expected_bytes = expected.encode("utf-8")
    if actual[: len(expected_bytes)] != expected_bytes or any(actual[len(expected_bytes) :]):
        raise ValueError(f"unexpected Add-On Content metadata at 0x{offset:X}")

    replacement_bytes = replacement.encode("utf-8")
    if len(replacement_bytes) + 1 > size:
        raise ValueError(f"Add-On Content text does not fit at 0x{offset:X}")
    data[offset : offset + size] = replacement_bytes + bytes(size - len(replacement_bytes))


def patch_dgs2_aoc_labels(source: bytes) -> bytes:
    """Translate the two DGS2 Add-On Content catalogue entries."""

    if len(source) != 0x260:
        raise ValueError("unexpected DGS2 ContentInfoArchive size")

    output = bytearray(source)
    fields = (
        (0x0D0, 0x40, "大逆転裁判２衣装", "Costume Pack"),
        (
            0x110,
            0x80,
            "大逆転裁判２衣装",
            "The Great Ace Attorney 2 - Costume Pack",
        ),
        (0x198, 0x40, "大逆転裁判２追加シナリオ", "Additional Episodes"),
        (
            0x1D8,
            0x80,
            "大逆転裁判２追加シナリオ",
            "The Great Ace Attorney 2 - Additional Episodes",
        ),
    )
    for offset, size, expected, replacement in fields:
        _replace_utf8_field(
            output,
            offset=offset,
            size=size,
            expected=expected,
            replacement=replacement,
        )
    return bytes(output)
