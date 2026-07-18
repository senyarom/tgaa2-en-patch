#!/usr/bin/env python3
"""Run every Court Record caption through the real C hook implementation."""

from __future__ import annotations

import argparse
import csv
import ctypes
import json
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path


CAPACITY = 256
MAXIMUM_WIDTH = 210
MAXIMUM_HEIGHT = 66
SIZE_RE = re.compile(r"^<SIZE (\d+)>")
TAG_RE = re.compile(r"<[^>]*>")


def load_entries(path: Path) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []

    def visit(value: object) -> None:
        if isinstance(value, dict):
            text = value.get("text")
            if isinstance(text, str):
                label = value.get("label", "?")
                result.append((str(label), text))
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(json.loads(path.read_text()))
    return result


def compile_host_library(repo: Path, output: Path) -> None:
    command = [
        "cc",
        "-std=c11",
        "-O2",
        "-Wall",
        "-Wextra",
        "-Werror",
    ]
    if sys.platform == "darwin":
        command.append("-dynamiclib")
    else:
        command.extend(("-shared", "-fPIC"))
    command.extend(
        (
            str(repo / "tests" / "court_record_hook_host.c"),
            "-o",
            str(output),
        )
    )
    subprocess.run(command, check=True)


def load_widths(path: Path) -> dict[str, int]:
    with path.open(newline="") as source:
        widths = {
            row["character"]: int(float(row["advance"]))
            for row in csv.DictReader(source)
        }
    widths["<"] = 9
    widths[">"] = 9
    widths["–"] = 7
    return widths


def normalized_visible(text: str) -> str:
    return " ".join(TAG_RE.sub("", text).split())


def verify_layout(
    source: str,
    output: str,
    widths: dict[str, int],
) -> int:
    match = SIZE_RE.match(output)
    if match is None:
        raise AssertionError(f"missing SIZE tag: {output!r}")
    size = int(match.group(1))
    if not 8 <= size <= 14:
        raise AssertionError(f"unexpected font size {size}: {output!r}")

    body = output[match.end() :]
    if normalized_visible(source) != normalized_visible(body):
        raise AssertionError(
            "visible text changed:\n"
            f"source: {source!r}\n"
            f"output: {output!r}"
        )

    line_height = (15 * size + 6) // 12
    lines = body.split("\r\n")
    if len(lines) * line_height > MAXIMUM_HEIGHT:
        raise AssertionError(
            f"height overflow: {len(lines)} * {line_height} > "
            f"{MAXIMUM_HEIGHT}: {output!r}"
        )

    for line in lines:
        visible_line = TAG_RE.sub("", line)
        line_width = sum(
            (widths.get(character, 14) * size + 6) // 12
            for character in visible_line
        )
        if line_width > MAXIMUM_WIDTH:
            raise AssertionError(
                f"width overflow: {line_width} > {MAXIMUM_WIDTH}: "
                f"{line!r}"
            )
    return size


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("metrics", type=Path)
    parser.add_argument("resources", type=Path, nargs="+")
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[1]
    entries: list[tuple[str, str, str]] = []
    for resource in args.resources:
        entries.extend(
            (resource.name, label, text)
            for label, text in load_entries(resource)
        )

    widths = load_widths(args.metrics)
    suffix = ".dylib" if sys.platform == "darwin" else ".so"
    with tempfile.TemporaryDirectory() as temporary:
        library_path = Path(temporary) / f"court_record_hook{suffix}"
        compile_host_library(repo, library_path)
        library = ctypes.CDLL(str(library_path))
        reflow = library.court_record_host_reflow
        reflow.argtypes = (
            ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_char),
            ctypes.c_uint16,
        )
        reflow.restype = ctypes.c_bool

        sizes: Counter[int] = Counter()
        maximum_output = 0
        for filename, label, text in entries:
            caption = f"<SIZE 14>{text}"
            encoded = caption.encode("utf-8")
            output_buffer = ctypes.create_string_buffer(CAPACITY)
            if not reflow(encoded, output_buffer, CAPACITY):
                raise AssertionError(f"C reflow failed: {filename}:{label}")
            output_bytes = output_buffer.value
            maximum_output = max(maximum_output, len(output_bytes) + 1)
            output = output_bytes.decode("utf-8")
            try:
                sizes[verify_layout(text, output, widths)] += 1
            except AssertionError as error:
                raise AssertionError(f"{filename}:{label}: {error}") from error

    print(f"C captions tested: {len(entries)}")
    print(f"Selected sizes: {dict(sorted(sizes.items(), reverse=True))}")
    print(f"Largest C output including NUL: {maximum_output}/{CAPACITY} bytes")


if __name__ == "__main__":
    main()
