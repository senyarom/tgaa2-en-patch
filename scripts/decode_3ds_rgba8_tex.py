#!/usr/bin/env python3
"""Decode and encode Morton-tiled RGBA8 TEX atlases used by TGAA 3DS."""

from __future__ import annotations

import argparse
import math
from pathlib import Path

from PIL import Image


HEADER_SIZE = 20


def morton_8x8(x: int, y: int) -> int:
    return (
        ((x & 1) << 0)
        | ((y & 1) << 1)
        | ((x & 2) << 1)
        | ((y & 2) << 2)
        | ((x & 4) << 2)
        | ((y & 4) << 3)
    )


def decode_rgba8_tex(
    blob: bytes, width: int | None = None, height: int | None = None
) -> Image.Image:
    if not blob.startswith(b"TEX\0") or len(blob) <= HEADER_SIZE:
        raise ValueError("expected a 3DS MT Framework TEX file")
    payload = blob[HEADER_SIZE:]
    if len(payload) % 4:
        raise ValueError("RGBA8 payload is not pixel-aligned")
    if width is None and height is None:
        side = math.isqrt(len(payload) // 4)
        width = height = side
    elif width is None or height is None:
        raise ValueError("width and height must be supplied together")
    if width * height * 4 != len(payload) or width % 8 or height % 8:
        raise ValueError("dimensions do not match the 8-pixel-tiled RGBA8 payload")

    output = bytearray(width * height * 4)
    tiles_per_row = width // 8
    for y in range(height):
        for x in range(width):
            tile = (y // 8) * tiles_per_row + (x // 8)
            pixel = tile * 64 + morton_8x8(x & 7, y & 7)
            alpha, blue, green, red = payload[pixel * 4 : pixel * 4 + 4]
            offset = (y * width + x) * 4
            output[offset : offset + 4] = bytes((red, green, blue, alpha))
    return Image.frombytes("RGBA", (width, height), bytes(output))


def decode_la44_tex(blob: bytes, width: int, height: int) -> Image.Image:
    """Decode MT Framework's one-byte luminance/alpha format (format 12)."""

    if not blob.startswith(b"TEX\0") or len(blob) <= HEADER_SIZE:
        raise ValueError("expected a 3DS MT Framework TEX file")
    payload = blob[HEADER_SIZE:]
    if width * height != len(payload) or width % 8 or height % 8:
        raise ValueError("dimensions do not match the 8-pixel-tiled LA44 payload")

    output = bytearray(width * height * 4)
    tiles_per_row = width // 8
    for y in range(height):
        for x in range(width):
            tile = (y // 8) * tiles_per_row + (x // 8)
            pixel = tile * 64 + morton_8x8(x & 7, y & 7)
            packed = payload[pixel]
            luminance = (packed & 0x0F) * 17
            alpha = (packed >> 4) * 17
            offset = (y * width + x) * 4
            output[offset : offset + 4] = bytes(
                (luminance, luminance, luminance, alpha)
            )
    return Image.frombytes("RGBA", (width, height), bytes(output))


def decode_tex(blob: bytes, width: int | None, height: int | None) -> Image.Image:
    """Decode the two texture formats used by the title-menu atlases."""

    if len(blob) < HEADER_SIZE:
        raise ValueError("truncated TEX file")
    pixel_format = blob[13]
    if pixel_format == 3:
        return decode_rgba8_tex(blob, width=width, height=height)
    if pixel_format == 12:
        if width is None or height is None:
            raise ValueError("width and height are required for LA44 textures")
        return decode_la44_tex(blob, width=width, height=height)
    raise ValueError(f"unsupported MT Framework TEX pixel format {pixel_format}")


def encode_rgba8_tex(image: Image.Image, template: bytes) -> bytes:
    """Encode an image as RGBA8 while preserving a compatible TEX header.

    TGAA's 3DS TEX files use 8x8 Morton tiles.  The texture header also carries
    engine-specific flags and packed dimensions, so callers provide an
    existing texture with the desired dimensions as the template.  Only its
    pixel-format byte is changed from the original format to RGBA8 (3).
    """

    if not template.startswith(b"TEX\0") or len(template) < HEADER_SIZE:
        raise ValueError("expected a 3DS MT Framework TEX template")

    rgba = image.convert("RGBA")
    width, height = rgba.size
    if width % 8 or height % 8:
        raise ValueError("RGBA8 texture dimensions must be multiples of 8")

    pixels = rgba.tobytes()
    payload = bytearray(width * height * 4)
    tiles_per_row = width // 8
    for y in range(height):
        for x in range(width):
            source = (y * width + x) * 4
            red, green, blue, alpha = pixels[source : source + 4]
            tile = (y // 8) * tiles_per_row + (x // 8)
            pixel = tile * 64 + morton_8x8(x & 7, y & 7)
            destination = pixel * 4
            payload[destination : destination + 4] = bytes(
                (alpha, blue, green, red)
            )

    header = bytearray(template[:HEADER_SIZE])
    header[13] = 3  # RGBA8 in MT Framework Mobile TEX files.
    return bytes(header) + bytes(payload)


def encode_la44_tex(image: Image.Image, template: bytes) -> bytes:
    """Encode an image in MT Framework's tiled 4-bit luminance/alpha format."""

    if not template.startswith(b"TEX\0") or len(template) < HEADER_SIZE:
        raise ValueError("expected a 3DS MT Framework TEX template")

    rgba = image.convert("RGBA")
    width, height = rgba.size
    if width % 8 or height % 8:
        raise ValueError("LA44 texture dimensions must be multiples of 8")

    pixels = rgba.tobytes()
    payload = bytearray(width * height)
    tiles_per_row = width // 8
    for y in range(height):
        for x in range(width):
            source = (y * width + x) * 4
            red, green, blue, alpha = pixels[source : source + 4]
            luminance_8 = (red * 54 + green * 183 + blue * 19 + 128) >> 8
            luminance_4 = (luminance_8 + 8) // 17
            alpha_4 = (alpha + 8) // 17
            tile = (y // 8) * tiles_per_row + (x // 8)
            pixel = tile * 64 + morton_8x8(x & 7, y & 7)
            payload[pixel] = (alpha_4 << 4) | luminance_4

    header = bytearray(template[:HEADER_SIZE])
    header[13] = 12
    return bytes(header) + bytes(payload)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--width", type=int)
    parser.add_argument("--height", type=int)
    args = parser.parse_args()
    image = decode_tex(args.input.read_bytes(), width=args.width, height=args.height)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    image.save(args.output)
    print(f"wrote {image.width}x{image.height} preview to {args.output}")


if __name__ == "__main__":
    main()
