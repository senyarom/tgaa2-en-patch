#!/usr/bin/env python3
"""Replace Scarlet Study's visible TGAA1 patch version with our build version."""

from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--from-version", default="ENG 2.4.1")
    parser.add_argument("--to-version", default="ENG 2.5.1")
    args = parser.parse_args()

    old = args.from_version.encode("ascii")
    new = args.to_version.encode("ascii")
    if len(old) != len(new):
        raise ValueError("replacement must have exactly the same byte length")
    blob = args.input.read_bytes()
    if blob.count(old) != 1:
        raise ValueError(f"expected exactly one {args.from_version!r} marker")
    output = blob.replace(old, new)
    if old in output or output.count(new) != 1:
        raise ValueError("version replacement verification failed")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(output)
    print(f"replaced {args.from_version!r} with {args.to_version!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
