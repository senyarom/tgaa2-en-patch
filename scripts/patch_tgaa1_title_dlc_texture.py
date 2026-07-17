#!/usr/bin/env python3
"""Restore the missing English DLC label in TGAA1's title-menu atlas."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from decode_3ds_rgba8_tex import encode_la44_tex, encode_rgba8_tex


# ``panel_text_02`` in title_top.gui samples this rectangle.  The Japanese
# texture contains the 電信付録 label here; Scarlet Study's English texture
# keeps the rectangle transparent, which leaves a working but invisible item.
DLC_RECT = (0, 62, 112, 92)


def add_dlc_label(image: Image.Image) -> Image.Image:
    output = image.convert("RGBA")
    if output.size != (256, 128):
        raise ValueError(f"expected a 256x128 title-panel atlas, got {output.size}")

    left, top, right, bottom = DLC_RECT
    label = Image.new("RGBA", (right - left, bottom - top), (0, 0, 0, 0))
    draw = ImageDraw.Draw(label)

    # Pillow embeds this font, so the generated bitmap is deterministic and
    # does not depend on fonts installed on the build machine.
    font = ImageFont.load_default(size=24)
    bounds = draw.textbbox((0, 0), "DLC", font=font, stroke_width=2)
    text_width = bounds[2] - bounds[0]
    text_height = bounds[3] - bounds[1]
    x = (right - left - text_width) // 2 - bounds[0]
    y = (bottom - top - text_height) // 2 - bounds[1]
    draw.text(
        (x, y),
        "DLC",
        font=font,
        fill=(245, 245, 245, 255),
        stroke_width=2,
        stroke_fill=(20, 20, 20, 255),
    )
    # Preserve every existing atlas pixel outside the glyphs themselves.
    # The DLC rectangle overlaps data sampled by highlight animations, so
    # replacing the whole transparent rectangle can create specks on the
    # neighbouring cards even though the label looks correct in isolation.
    output.paste(label, (left, top), label)
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_png", type=Path)
    parser.add_argument("template_tex", type=Path)
    parser.add_argument("output_tex", type=Path)
    parser.add_argument("--preview", type=Path)
    args = parser.parse_args()

    image = add_dlc_label(Image.open(args.source_png))
    template = args.template_tex.read_bytes()
    if template[13] == 12:
        blob = encode_la44_tex(image, template)
        format_name = "LA44"
    elif template[13] == 3:
        blob = encode_rgba8_tex(image, template)
        format_name = "RGBA8"
    else:
        raise ValueError(f"unsupported title-panel format {template[13]}")
    args.output_tex.parent.mkdir(parents=True, exist_ok=True)
    args.output_tex.write_bytes(blob)
    if args.preview:
        args.preview.parent.mkdir(parents=True, exist_ok=True)
        image.save(args.preview)

    print(f"wrote {format_name} DLC-label texture to {args.output_tex}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
